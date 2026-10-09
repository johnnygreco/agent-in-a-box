// P1: P0 with one edit. The method predicate of get-reference is broadened
// from GET to GET or POST. Endpoint, path, and connection policy are unchanged.

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
