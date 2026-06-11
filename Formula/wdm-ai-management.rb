class WdmAiManagement < Formula
  desc "Manage AI agents, skills, MCP servers, rules, workflows, hooks, and harnesses"
  homepage "https://github.com/WD-Mitchell/WDM-AI-Management"
  url "https://github.com/WD-Mitchell/WDM-AI-Management/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "REPLACE_WITH_RELEASE_SHA256"
  license "MIT"

  depends_on "python@3.14"

  def install
    libexec.install Dir["*"]
    bin.install_symlink libexec/"bin/wdm" => "wdm"
    bin.install_symlink libexec/"bin/wdm-ai" => "wdm-ai"
  end

  def post_install
    system bin/"wdm", "ai", "bootstrap", "--quiet"
  end

  test do
    system bin/"wdm", "ai", "--help"
  end
end
