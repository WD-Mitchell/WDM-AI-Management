require "language/python"

class WdmAiManagement < Formula
  include Language::Python::Virtualenv

  desc "Manage AI agents, skills, MCP servers, rules, workflows, hooks, and harnesses"
  homepage "https://github.com/WD-Mitchell/WDM-AI-Management"
  url "https://github.com/WD-Mitchell/WDM-AI-Management/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "REPLACE_WITH_RELEASE_SHA256"
  license "MIT"

  depends_on "python@3.14"

  resource "PyYAML" do
    url "https://files.pythonhosted.org/packages/05/8e/961c0007c59b8dd7729d542c61a4d537767a59645b82a0b521206e1e25c2/pyyaml-6.0.3.tar.gz"
    sha256 "d76623373421df22fb4cf8817020cbb7ef15c725b9d5e45f17e189bfc384190f"
  end

  def install
    libexec.install Dir["*"]
    venv = virtualenv_create(libexec/"venv", "python3.14")
    venv.pip_install resources

    (bin/"wdm-ai").write <<~EOS
      #!/bin/bash
      export PYTHONPATH="#{libexec}:$PYTHONPATH"
      exec "#{libexec}/venv/bin/python" "#{libexec}/bin/wdm-ai" "$@"
    EOS
  end

  test do
    system bin/"wdm-ai", "--help"
  end
end
