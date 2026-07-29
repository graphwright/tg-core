I understand you want a Linux/Bash Docker setup that still uses your own GitHub identity, and whether secrets are required. I’ll give you the secure setup options (SSH agent forwarding vs HTTPS token), what credentials you do and don’t need, and a minimal workflow you can run today.

Use SSH agent forwarding. It gives your container a Linux/Bash environment and lets Git inside the container authenticate as you, without copying private keys into the container.

Short answer to your secrets question:
- You do not need your GitHub password.
- You do not need a GitHub API key for normal git clone/pull/push over SSH.
- You only need a token (PAT) if you choose HTTPS auth, use GitHub API/gh auth flows, or access private package registries.

Recommended setup (macOS + Docker Desktop)

1. Set up SSH auth on your host (one time)
- Create key if needed: ssh-keygen -t ed25519 -C "you@example.com"
- Add key to ssh-agent: ssh-add ~/.ssh/id_ed25519
- Add the public key to GitHub (Settings → SSH and GPG keys)
- Verify on host: ssh -T git@github.com

2. Start a container with agent forwarding
- This mounts your project, forwards host SSH agent, and shares your git identity config.

Command:
docker run --rm -it \
  -v "$PWD":/work \
  -w /work \
  -v /run/host-services/ssh-auth.sock:/ssh-agent \
  -e SSH_AUTH_SOCK=/ssh-agent \
  -v "$HOME/.gitconfig":/root/.gitconfig:ro \
  ubuntu:24.04 bash

3. Inside container
- Install git + ssh client if image is minimal:
apt-get update && apt-get install -y git openssh-client
- Test identity:
ssh -T git@github.com
- Use SSH remotes, for example:
git clone git@github.com:OWNER/REPO.git

Why this is best
- Your private key never enters the container filesystem.
- If container is deleted, no long-lived credential is left behind.
- Your personal GitHub identity and permissions are used.

What not to do
- Do not bake tokens or keys into Dockerfile layers.
- Do not commit .env files with secrets.
- Avoid mounting ~/.ssh private keys directly unless you must.

If you want, I can also give you:
1. A docker-compose version of the same setup.
2. A VS Code Dev Container configuration that forwards your SSH agent automatically.
