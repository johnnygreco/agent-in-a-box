// P5: P0 restored through a refactor that keeps every decision the same.
// The method test moves into an unless clause.

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
when { context.path == "/reference" }
unless { context.method != "GET" };
