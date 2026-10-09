//! agent-in-a-box-cedar: a JSON bridge to the pinned Cedar authorizer and Cedar SymCC.
//!
//! Protocol: read one JSON command from stdin, write one JSON document to
//! stdout, exit 0. The document is `{"ok": true, "result": ...}` or
//! `{"ok": false, "error": {"kind": ..., "message": ...}}`. Any other exit
//! status or unparsable output is a bridge failure; the Python adapters turn
//! that into a deny (evaluation) or "no conclusion" (analysis), never an allow
//! or a proof.
//!
//! Why this exists instead of parsing `cedar` CLI output: see decisions/0002.
//! The bridge adds no policy semantics. It parses, validates, authorizes, and
//! runs SymCC queries, and serializes what those libraries return.

use std::io::Read;
use std::process::ExitCode;
use std::str::FromStr;

use cedar_policy::{
    AuthorizationError, Authorizer, Context, Decision, Effect, Entities, EntityTypeName, EntityUid, PolicyId,
    PolicySet, Request, RequestEnv, Schema, ValidationMode, Validator,
};
use cedar_policy_symcc::err::Error as SymccError;
use cedar_policy_symcc::solver::{LocalSolver, Solver, WriterSolver};
use cedar_policy_symcc::{CedarSymCompiler, CompiledPolicy, CompiledPolicySet, Env};
use serde::Deserialize;
use serde_json::{json, Value};

/// Pinned SymCC version (Cargo.toml pins `=0.6.0`; SymCC exposes no version function).
const SYMCC_VERSION: &str = "0.6.0";

#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
enum Command {
    Version,
    Validate { schema: String, policies: String },
    Authorize(AuthorizeArgs),
    RequestEnvs { schema: String },
    Analyze(AnalyzeArgs),
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct AuthorizeArgs {
    schema: String,
    policies: String,
    request: RequestJson,
    entities: Value,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RequestJson {
    principal: Value,
    action: Value,
    resource: Value,
    context: Value,
}

#[derive(Deserialize, Clone, Copy)]
#[serde(rename_all = "snake_case")]
enum Property {
    Implies,
    Equivalent,
    Disjoint,
    AlwaysAllows,
    AlwaysDenies,
    NeverErrors,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct AnalyzeArgs {
    schema: String,
    property: Property,
    policies: String,
    #[serde(default)]
    other_policies: Option<String>,
    request_env: RequestEnvJson,
    solver: SolverJson,
    #[serde(default)]
    emit_smtlib: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RequestEnvJson {
    principal_type: String,
    action: Value,
    resource_type: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SolverJson {
    path: String,
    #[serde(default)]
    args: Vec<String>,
}

/// A handled failure: reported as `{"ok": false, ...}` with a stable kind.
struct Failure {
    kind: &'static str,
    message: String,
}

fn fail(kind: &'static str, message: impl Into<String>) -> Failure {
    Failure { kind, message: message.into() }
}

/// Display of an error plus its source chain, so nested causes are not lost.
fn describe(err: &dyn std::error::Error) -> String {
    let mut text = err.to_string();
    let mut source = err.source();
    while let Some(cause) = source {
        text.push_str(": ");
        text.push_str(&cause.to_string());
        source = cause.source();
    }
    text
}

fn load_schema(src: &str) -> Result<Schema, Failure> {
    Schema::from_cedarschema_str(src)
        .map(|(schema, _warnings)| schema)
        .map_err(|e| fail("schema", describe(&e)))
}

/// Parse policies and give each the id from its `@id("...")` annotation.
///
/// Cedar assigns positional ids (`policy0`, ...) to parsed text; determining
/// policy ids are only useful to a learner if they are the authored names.
fn load_policies(src: &str) -> Result<PolicySet, Failure> {
    let parsed = PolicySet::from_str(src).map_err(|e| fail("parse", describe(&e)))?;
    if let Some(template) = parsed.templates().next() {
        return Err(fail(
            "unsupported",
            format!("policy templates are not supported ({})", template.id()),
        ));
    }
    let mut named = PolicySet::new();
    for policy in parsed.policies() {
        let id = policy.annotation("id").ok_or_else(|| {
            fail("parse", format!("every policy needs an @id(\"...\") annotation:\n{policy}"))
        })?;
        named
            .add(policy.new_id(PolicyId::new(id)))
            .map_err(|e| fail("parse", format!("@id(\"{id}\"): {}", describe(&e))))?;
    }
    Ok(named)
}

fn uid(value: Value, field: &str) -> Result<EntityUid, Failure> {
    EntityUid::from_json(value).map_err(|e| fail("request", format!("{field}: {}", describe(&e))))
}

fn uid_json(uid: &EntityUid) -> Value {
    json!({"type": uid.type_name().to_string(), "id": uid.id().unescaped()})
}

fn effect_name(effect: Effect) -> &'static str {
    match effect {
        Effect::Permit => "permit",
        Effect::Forbid => "forbid",
    }
}

fn version() -> Value {
    json!({
        "bridge": env!("CARGO_PKG_VERSION"),
        "cedar_policy": cedar_policy::get_sdk_version().to_string(),
        "cedar_language": cedar_policy::get_lang_version().to_string(),
        "cedar_policy_symcc": SYMCC_VERSION,
    })
}

fn validate(schema: &str, policies: &str) -> Result<Value, Failure> {
    let schema = load_schema(schema)?;
    let pset = load_policies(policies)?;
    let result = Validator::new(schema).validate(&pset, ValidationMode::Strict);
    let errors: Vec<Value> = result
        .validation_errors()
        .map(|e| json!({"policy_id": e.policy_id().to_string(), "message": describe(e)}))
        .collect();
    let warnings: Vec<Value> = result
        .validation_warnings()
        .map(|w| json!({"policy_id": w.policy_id().to_string(), "message": describe(w)}))
        .collect();
    let mut listed: Vec<Value> = pset
        .policies()
        .map(|p| {
            json!({
                "id": p.id().to_string(),
                "effect": effect_name(p.effect()),
                "text": p.to_string(),
                "json": p.to_json().map_err(|e| fail("parse", describe(&e))).ok(),
            })
        })
        .collect();
    listed.sort_by(|a, b| a["id"].as_str().cmp(&b["id"].as_str()));
    Ok(json!({
        "valid": errors.is_empty(),
        "errors": errors,
        "warnings": warnings,
        "policies": listed,
    }))
}

fn authorize(args: AuthorizeArgs) -> Result<Value, Failure> {
    let schema = load_schema(&args.schema)?;
    let pset = load_policies(&args.policies)?;
    let principal = uid(args.request.principal, "principal")?;
    let action = uid(args.request.action, "action")?;
    let resource = uid(args.request.resource, "resource")?;
    let context = Context::from_json_value(args.request.context, Some((&schema, &action)))
        .map_err(|e| fail("request", format!("context: {}", describe(&e))))?;
    let request = Request::new(principal, action, resource, context, Some(&schema))
        .map_err(|e| fail("request", describe(&e)))?;
    let entities = Entities::from_json_value(args.entities, Some(&schema))
        .map_err(|e| fail("entities", describe(&e)))?;

    let response = Authorizer::new().is_authorized(&request, &pset, &entities);
    let mut determining: Vec<String> =
        response.diagnostics().reason().map(ToString::to_string).collect();
    determining.sort();
    let errors: Vec<Value> = response
        .diagnostics()
        .errors()
        .map(|e| {
            let AuthorizationError::PolicyEvaluationError(inner) = e;
            json!({"policy_id": inner.policy_id().to_string(), "message": describe(e)})
        })
        .collect();
    let decision = match response.decision() {
        Decision::Allow => "allow",
        Decision::Deny => "deny",
    };
    Ok(json!({"decision": decision, "determining": determining, "errors": errors}))
}

fn request_envs(schema: &str) -> Result<Value, Failure> {
    let schema = load_schema(schema)?;
    let mut envs: Vec<Value> = schema
        .request_envs()
        .map(|env| {
            json!({
                "principal_type": env.principal().to_string(),
                "action": uid_json(env.action()),
                "resource_type": env.resource().to_string(),
            })
        })
        .collect();
    envs.sort_by_key(|e| e.to_string());
    Ok(json!({"request_envs": envs}))
}

/// The concrete counterexample SymCC returned, serialized without change.
fn witness_json(env: &Env) -> Result<Value, Failure> {
    let request = &env.request;
    let context = match request.context() {
        Some(ctx) => ctx.to_json_value().map_err(|e| fail("witness", describe(&e)))?,
        None => Value::Null,
    };
    Ok(json!({
        "request": {
            "principal": request.principal().map(|u| uid_json(&u)),
            "action": request.action().map(|u| uid_json(&u)),
            "resource": request.resource().map(|u| uid_json(&u)),
            "context": context,
        },
        "entities": env.entities.to_json_value().map_err(|e| fail("witness", describe(&e)))?,
        "display": env.to_string(),
    }))
}

/// What one property query compiled to: whole sets, or one policy at a time.
enum Compiled {
    Sets(CompiledPolicySet, Option<CompiledPolicySet>),
    Singles(Vec<(String, CompiledPolicy)>),
}

/// Runs one property query. `Ok(None)` means the solver found no
/// counterexample (UNSAT); `Ok(Some(..))` carries the counterexample (SAT).
async fn check<S: Solver>(
    compiler: &mut CedarSymCompiler<S>,
    property: Property,
    compiled: &Compiled,
) -> Result<Option<(Option<String>, Env)>, SymccError> {
    let found = |env: Option<Env>| env.map(|e| (None, e));
    match (property, compiled) {
        (Property::NeverErrors, Compiled::Singles(policies)) => {
            for (id, policy) in policies {
                if let Some(env) = compiler.check_never_errors_with_counterexample_opt(policy).await? {
                    return Ok(Some((Some(id.clone()), env)));
                }
            }
            Ok(None)
        }
        (Property::AlwaysAllows, Compiled::Sets(a, _)) => {
            Ok(found(compiler.check_always_allows_with_counterexample_opt(a).await?))
        }
        (Property::AlwaysDenies, Compiled::Sets(a, _)) => {
            Ok(found(compiler.check_always_denies_with_counterexample_opt(a).await?))
        }
        (Property::Implies, Compiled::Sets(a, Some(b))) => {
            Ok(found(compiler.check_implies_with_counterexample_opt(a, b).await?))
        }
        (Property::Equivalent, Compiled::Sets(a, Some(b))) => {
            Ok(found(compiler.check_equivalent_with_counterexample_opt(a, b).await?))
        }
        (Property::Disjoint, Compiled::Sets(a, Some(b))) => {
            Ok(found(compiler.check_disjoint_with_counterexample_opt(a, b).await?))
        }
        _ => Err(SymccError::NoPolicies),
    }
}

fn symcc_kind(err: &SymccError) -> &'static str {
    match err {
        SymccError::SolverUnknown => "unknown",
        SymccError::PolicyNotWellTyped { .. } => "not_well_typed",
        SymccError::SolverError(_) => "solver",
        SymccError::DecodeModel(_) | SymccError::ConcretizeError(_) | SymccError::ModelInvalid { .. } => {
            "witness"
        }
        _ => "unsupported",
    }
}

fn compile(args: &AnalyzeArgs, schema: &Schema, env: &RequestEnv) -> Result<Compiled, SymccError> {
    let first = load_policies(&args.policies).map_err(|_| SymccError::NoPolicies)?;
    if let Property::NeverErrors = args.property {
        let mut singles = Vec::new();
        for policy in first.policies() {
            singles.push((policy.id().to_string(), CompiledPolicy::compile(policy, env, schema)?));
        }
        singles.sort_by(|a, b| a.0.cmp(&b.0));
        return Ok(Compiled::Singles(singles));
    }
    let a = CompiledPolicySet::compile(&first, env, schema)?;
    let b = match &args.other_policies {
        Some(src) => {
            let second = load_policies(src).map_err(|_| SymccError::NoPolicies)?;
            Some(CompiledPolicySet::compile(&second, env, schema)?)
        }
        None => None,
    };
    Ok(Compiled::Sets(a, b))
}

fn analyze(args: AnalyzeArgs) -> Result<Value, Failure> {
    let schema = load_schema(&args.schema)?;
    load_policies(&args.policies)?;
    if let Some(src) = &args.other_policies {
        load_policies(src)?;
    }
    let two_sets = matches!(args.property, Property::Implies | Property::Equivalent | Property::Disjoint);
    if two_sets != args.other_policies.is_some() {
        return Err(fail("command", "other_policies is required exactly for two-set properties"));
    }
    let principal_type = EntityTypeName::from_str(&args.request_env.principal_type)
        .map_err(|e| fail("command", describe(&e)))?;
    let resource_type = EntityTypeName::from_str(&args.request_env.resource_type)
        .map_err(|e| fail("command", describe(&e)))?;
    let action = uid(args.request_env.action.clone(), "request_env.action")?;
    let env = RequestEnv::new(principal_type, action, resource_type);

    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|e| fail("internal", e.to_string()))?;
    runtime.block_on(async {
        let compiled = match compile(&args, &schema, &env) {
            Ok(compiled) => compiled,
            Err(e) => return Ok(json!({"status": "error", "error": {"kind": symcc_kind(&e), "message": describe(&e)}})),
        };

        let smtlib = if args.emit_smtlib {
            let mut writer = CedarSymCompiler::new(WriterSolver { w: Vec::<u8>::new() })
                .map_err(|e| fail("internal", describe(&e)))?;
            let _ = check(&mut writer, args.property, &compiled).await;
            Some(String::from_utf8_lossy(&writer.solver().w).into_owned())
        } else {
            None
        };

        let mut command = tokio::process::Command::new(&args.solver.path);
        command.args(["--lang", "smt"]).args(&args.solver.args);
        let solver = LocalSolver::from_command(&mut command).map_err(|e| fail("solver", describe(&e)))?;
        let mut compiler = CedarSymCompiler::new(solver).map_err(|e| fail("solver", describe(&e)))?;
        let outcome = check(&mut compiler, args.property, &compiled).await;
        let _ = compiler.solver_mut().clean_up().await;

        let mut doc = match outcome {
            Ok(None) => json!({"status": "unsat"}),
            Ok(Some((policy_id, env))) => {
                json!({"status": "sat", "witness": witness_json(&env)?, "witness_policy_id": policy_id})
            }
            Err(SymccError::SolverUnknown) => json!({"status": "unknown"}),
            Err(e) => json!({"status": "error", "error": {"kind": symcc_kind(&e), "message": describe(&e)}}),
        };
        if let Some(script) = smtlib {
            doc["smtlib"] = Value::String(script);
        }
        Ok(doc)
    })
}

fn dispatch(command: Command) -> Result<Value, Failure> {
    match command {
        Command::Version => Ok(version()),
        Command::Validate { schema, policies } => validate(&schema, &policies),
        Command::Authorize(args) => authorize(args),
        Command::RequestEnvs { schema } => request_envs(&schema),
        Command::Analyze(args) => analyze(args),
    }
}

fn main() -> ExitCode {
    let mut input = String::new();
    let outcome = match std::io::stdin().read_to_string(&mut input) {
        Ok(_) => serde_json::from_str::<Command>(&input)
            .map_err(|e| fail("command", e.to_string()))
            .and_then(dispatch),
        Err(e) => Err(fail("command", e.to_string())),
    };
    let document = match outcome {
        Ok(result) => json!({"ok": true, "result": result}),
        Err(f) => json!({"ok": false, "error": {"kind": f.kind, "message": f.message}}),
    };
    println!("{document}");
    ExitCode::SUCCESS
}
