# Publishing CommitEcho v0.2.0 to PyPI

The goal is `python -m pip install commitecho` with Python 3.12+ and Git 2.34+.
Publication is pending. The public PyPI and TestPyPI JSON endpoints both returned
HTTP 404 for `commitecho` on 2026-10-04. This is not a name reservation; the upload
is the final availability check. No credentials or publication are included in CI.

## 1. Create accounts (you)

Register at [PyPI](https://pypi.org/account/register/), verify your email, enable
two-factor authentication, and save recovery codes. If rehearsing first, create
a separate [TestPyPI account](https://test.pypi.org/account/register/); its account
and token are independent of production PyPI.

For a first manual upload, create an entire-account API token in the selected
index's account settings. Once the project exists, replace it with a token scoped
to `commitecho`, then revoke the broad token. Save the token when PyPI displays
it; that value is shown only once. Keep tokens in your local credential store or
enter them at Twine's hidden prompt, including the `pypi-` prefix. Do not paste
tokens into chat, commit them, or put them in command arguments.

## 2. Review and commit the release (I can do this when requested)

Review the release notes, MIT license, package version, and portable plugin.
Commit only intended files and the prepared CommitEcho decision record. Run the
full test suite, including `tests/test_eval_gate.py`, which builds its own
fixtures and checks capture, linkage, retrieval, and baseline comparisons.
Push the branch when authorized and wait for all four CI jobs (Windows/Linux,
minimum/latest MCP) to pass. Merge according to your repository rules. The CI
badge becomes meaningful after GitHub executes the workflow.

I can commit with a verified CommitEcho record, push the branch, inspect CI,
and prepare an annotated `v0.2.0` tag when you request those actions. Do not
publish artifacts from a release whose required checks failed.

## 3. Build and validate (I can do this)

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install build twine
.\.venv\Scripts\python.exe -m build --outdir dist/release-v0.2.0
.\.venv\Scripts\python.exe -m twine check --strict dist/release-v0.2.0/commitecho-0.2.0-py3-none-any.whl dist/release-v0.2.0/commitecho-0.2.0.tar.gz
Get-FileHash dist/release-v0.2.0/commitecho-0.2.0* -Algorithm SHA256
```

Keep these two artifacts together. Validate wheel imports, CLI help/version,
init/setup/doctor, all four generated MCP profiles, local/portable plugin
launches, and capture/commit/verify/index/restart/Git-only clone recall in a
fresh environment outside the source tree without `PYTHONPATH`. The release
notes record completed validation and its limits. Metadata checks also confirm
that the MIT license and canonical skill are packaged and private local files
are excluded.

## 4. Optional TestPyPI rehearsal (you enter the token; I can validate)

Run the upload yourself in a terminal, entering the TestPyPI token at the hidden
prompt. Twine accepts tokens with username `__token__`:

```powershell
.\.venv\Scripts\python.exe -m twine upload --repository testpypi --username __token__ dist/release-v0.2.0/commitecho-0.2.0-py3-none-any.whl dist/release-v0.2.0/commitecho-0.2.0.tar.gz
```

For a clean rehearsal, first install runtime dependencies from production PyPI,
then fetch only CommitEcho from TestPyPI. Avoid combining indexes for dependency
resolution:

```powershell
py -3.12 -m venv .test-tmp-testpypi
.\.test-tmp-testpypi\Scripts\python.exe -m pip install "mcp>=2.2.0,<3" "pydantic>=2.9" "click>=8.1" "tomlkit>=0.13,<1"
.\.test-tmp-testpypi\Scripts\python.exe -m pip install --index-url https://test.pypi.org/simple/ --no-deps commitecho==0.2.0
.\.test-tmp-testpypi\Scripts\python.exe -m commitecho --version
```

I can run the installation and protocol checks after your upload. TestPyPI may
remove projects; it is not the production release.

## 5. Upload to production PyPI (explicit publication step)

Use the same validated artifacts, with the production PyPI token:

```powershell
.\.venv\Scripts\python.exe -m twine upload --repository-url https://upload.pypi.org/legacy/ --username __token__ dist/release-v0.2.0/commitecho-0.2.0-py3-none-any.whl dist/release-v0.2.0/commitecho-0.2.0.tar.gz
```

You can run this and enter the token interactively. Alternatively, ask me to
publish `commitecho==0.2.0` to production PyPI after configuring credentials
securely for the publishing process. On this Windows host, you can save the token
in Twine's supported keyring yourself:

```powershell
.\.venv\Scripts\python.exe -m keyring set https://upload.pypi.org/legacy/ __token__
```

Paste the token only at the hidden prompt. For TestPyPI, use
`https://test.pypi.org/legacy/` instead. If the operating system requests access to
its credential store, complete that dialog yourself. I can then run Twine with
`--non-interactive`, which fails if the credential cannot be retrieved, without
reading or printing the token. If no usable credential is configured, perform
the token-entry/upload step yourself.

A released filename cannot be replaced; corrections need a new version. Upload
only the two named artifacts, not all historical files under `dist/`. If an upload
partially succeeds, check which files are already present and upload only the
missing file; do not rebuild different bytes under the same released filename.

## 6. Verify the public install and finish the release (I can do this)

From a fresh environment, install from production PyPI:

```powershell
py -3.12 -m venv .test-tmp-pypi
.\.test-tmp-pypi\Scripts\python.exe -m pip install --index-url https://pypi.org/simple/ commitecho==0.2.0
.\.test-tmp-pypi\Scripts\python.exe -m commitecho --version
```

I can verify the public artifact hashes and installed MCP workflow, then update
README/release notes with the actual publication date and package page. When
authorized, I can push the annotated release tag and create the GitHub release
with the wheel and source archive. Users then install with `pip install
commitecho`; source-checkout installation remains a developer option.

## What to ask me, in order

Account registration, email verification, two-factor authentication, and entering
secrets are your steps. The following prompts delegate the remaining work:

| After | Ask me |
| --- | --- |
| Reviewing the local release changes | “Commit the v0.2.0 release preparation with its verified CommitEcho record and push the branch.” |
| The branch is pushed | “Check GitHub CI and resolve any failures before release.” |
| Required checks pass and the intended release commit is selected | “Build the final v0.2.0 wheel and source archive, validate them, and record their SHA256 hashes.” |
| You upload those artifacts to TestPyPI | “Verify the TestPyPI installation and installed MCP workflows.” |
| Production token is stored securely and the artifact hashes are accepted | “Publish these validated commitecho 0.2.0 artifacts to production PyPI.” |
| Production upload completes | “Verify pip install commitecho from PyPI, update the publication status, and push the release tag and GitHub release.” |

Skip the TestPyPI row if you choose to publish directly after local validation.
Report the account/index readiness or upload result, never the token itself.

## Future releases

A [PyPI Trusted Publisher](https://docs.pypi.org/trusted-publishers/) can replace
long-lived tokens with GitHub Actions identity. If you want automated releases,
ask me to add a separate publishing workflow, then configure its exact owner,
repository, workflow filename, and protected environment in PyPI. PR test CI
needs no PyPI credentials and does not publish packages.

## References

- [PyPA packaging and upload guide](https://packaging.python.org/en/latest/tutorials/packaging-projects/)
- [PyPI API tokens and two-factor authentication](https://pypi.org/help/)
- [Twine keyring credential storage](https://twine.readthedocs.io/en/stable/#keyring-support)
- [PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/)
- [GitHub Actions workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
