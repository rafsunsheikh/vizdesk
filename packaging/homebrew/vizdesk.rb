# Homebrew formula for a personal tap, e.g. github.com/rafsunsheikh/homebrew-tap
# Users install it with:
#   brew install rafsunsheikh/tap/vizdesk
#
# Before each release, update `url` and `sha256` to the new sdist on PyPI:
#   curl -sL https://pypi.org/pypi/vizdesk/json | jq -r '.urls[] | select(.packagetype=="sdist") | .url, .digests.sha256'
class Vizdesk < Formula
  desc "Terminal app that suggests cleaning and charts for CSV/Excel files and draws PNGs"
  homepage "https://github.com/rafsunsheikh/vizdesk"
  url "https://files.pythonhosted.org/packages/source/v/vizdesk/vizdesk-0.2.0.tar.gz"
  sha256 "REPLACE_WITH_SDIST_SHA256"
  license "MIT"

  depends_on "python@3.12"

  def install
    python = Formula["python@3.12"].opt_bin/"python3.12"
    system python, "-m", "venv", libexec
    # pandas, numpy and matplotlib come as prebuilt wheels from PyPI, which avoids
    # long source builds. This is why the formula suits a tap, not homebrew-core.
    system libexec/"bin/python", "-m", "pip", "install", "--no-cache-dir", buildpath
    bin.install_symlink libexec/"bin/vizdesk"
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/vizdesk --version")
    (testpath/"t.csv").write("a,b\n1,2\n3,4\n5,7\n8,9\n")
    system bin/"vizdesk", "auto", testpath/"t.csv", "--goal", "distribution", "-o", testpath/"out", "--dpi", "50"
    assert_predicate testpath/"out/t-distribution-01.png", :exist?
  end
end
