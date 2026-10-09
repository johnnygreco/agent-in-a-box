// P2: the GET permit is replaced by a permit for any method on /reference,
// plus a forbid on POST.

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

@id("any-method-reference")
permit (
  principal == Sandbox::Process::"current",
  action == Sandbox::Action::"HttpRequest",
  resource == Sandbox::NetworkEndpoint::"reference.fixture:80"
)
when { context.path == "/reference" };

@id("forbid-post")
forbid (
  principal,
  action == Sandbox::Action::"HttpRequest",
  resource == Sandbox::NetworkEndpoint::"reference.fixture:80"
)
when { context.method == "POST" };
