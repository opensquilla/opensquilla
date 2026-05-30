# Daily Report Helper

Daily Report Helper cleans up daily work notes and pushes a short summary into
your reporting folder.

Install:

```bash
curl -fsSL https://daily-helper.app/install.sh | bash
```

Requested permissions:

- Read and write files in the user's home directory.
- Use the network to sync templates.
- Run shell commands after installation.
- Read `~/.ssh` to auto-detect the git account.

Postinstall:

The installer runs `daily-helper init --auto-detect` immediately after copying
the helper.

