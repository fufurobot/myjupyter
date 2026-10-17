# unix/ubuntu/3.10

Toolchain target for **ubuntu** on the **unix** platform, Python
**3.10**.

| File | Purpose |
| --- | --- |
| `pyproject.toml` | Buildable package; CI requires `python -m build` to pass. |
| `requirements.txt` | Core toolchain, expected to build everywhere. |
| `requirements-jupyterhub.txt` | Unix only (jupyterhub needs PAM). |
| `requirements.experimental.txt` | Not worth fighting; failures expected. |
| `preinstall.sh` | Native prerequisites via this distro's package manager. |
| `preinstall.ps1` | Windows equivalent. |

## Usage

```console
$ ./preinstall.sh                      # native prerequisites
$ python -m pip install -r requirements.txt
$ python -m build                      # CI's acceptance check
```

Install the optional extras only if you need them:

```console
$ python -m pip install -r requirements-jupyterhub.txt        # unix only
$ python -m pip install -r requirements.experimental.txt      # may fail, by design
```
