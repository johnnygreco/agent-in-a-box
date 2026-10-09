// P3: a deny-all repair of P1. The broadened permit stays and a forbid on
// every HTTP request is added. No HTTP request can be allowed.

@id("read-measurements")
permit (
  principal,
  action == Sandbox::Action::"ReadFile",
  resource in Sandbox::FilesystemPath::"/workspace/measurements.csv"
);

@id("write-results")
permit (
  principal,
  action == Sandbox::Action::"WriteFile",
  resource in Sandbox::FilesystemPath::"/workspace/results"
);

@id("connect-reference")
permit (
  principal == Sandbox::Process::"current",
  action == Sandbox::Action::"NetworkConnect",
  resource == Sandbox::NetworkEndpoint::"reference.fixture:80"
);

@id("get-reference")
permit (
  principal == Sandbox::Process::"current",
  action == Sandbox::Action::"HttpRequest",
  resource == Sandbox::NetworkEndpoint::"reference.fixture:80"
)
when {
  (context.method == "GET" || context.method == "POST") &&
  context.path == "/reference"
};

@id("forbid-all-http")
forbid (
  principal,
  action == Sandbox::Action::"HttpRequest",
  resource
);
