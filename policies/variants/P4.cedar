// P4: P0 plus a forbid on /reference and a second permit for GET /reference.

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
when { context.method == "GET" && context.path == "/reference" };

@id("forbid-reference")
forbid (
  principal,
  action == Sandbox::Action::"HttpRequest",
  resource == Sandbox::NetworkEndpoint::"reference.fixture:80"
)
when { context.path == "/reference" };

@id("get-reference-again")
permit (
  principal == Sandbox::Process::"current",
  action == Sandbox::Action::"HttpRequest",
  resource == Sandbox::NetworkEndpoint::"reference.fixture:80"
)
when { context.method == "GET" && context.path == "/reference" };
