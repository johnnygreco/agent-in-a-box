// P6: P0 with the connection endpoint moved from the resource scope into a
// when clause. Cedar decisions are the same as P0. The derived route
// eligibility is not: the proxy routes only to endpoints that a
// NetworkConnect permit names in its scope, because a route must be known
// before any request arrives.

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
  resource
)
when { resource == Sandbox::NetworkEndpoint::"reference.fixture:80" };

@id("get-reference")
permit (
  principal == Sandbox::Process::"current",
  action == Sandbox::Action::"HttpRequest",
  resource == Sandbox::NetworkEndpoint::"reference.fixture:80"
)
when { context.method == "GET" && context.path == "/reference" };
