ARG UBUNTU_VERSION=24.04
FROM ubuntu:${UBUNTU_VERSION}

ARG APT_INSTALL_FLAGS="-y --no-install-recommends"
ARG DEFAULT_WORKDIR=/work
ARG DEFAULT_SSH_KEY_PATH=/root/.ssh/ww_id_ed25519
ARG DEFAULT_GIT_SSH_OPTIONS="-o IdentitiesOnly=yes -o StrictHostKeyChecking=yes"

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    WORKDIR_PATH=${DEFAULT_WORKDIR} \
    SSH_KEY_PATH=${DEFAULT_SSH_KEY_PATH} \
    GIT_SSH_OPTIONS=${DEFAULT_GIT_SSH_OPTIONS}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Basic Linux/Bash dev tools plus Git + SSH for GitHub operations.
RUN apt update
RUN apt install ${APT_INSTALL_FLAGS} \
        bash \
        ca-certificates \
        curl \
        git \
        less \
        openssh-client \
        vim \
        zip \
        unzip \
        zsh \
        python3 \
        python3-venv \
        python3-pip \
        python3-pdm-backend \
    && rm -rf /var/lib/apt/lists/*
RUN curl -sSL https://pdm-project.org/install.sh | bash

RUN mkdir -p /root/.ssh "${WORKDIR_PATH}" \
    && chmod 0700 /root/.ssh

# Make plain `ssh -T git@github.com` use the mounted custom key path.
RUN mkdir -p /etc/ssh/ssh_config.d \
        && printf '%s\n' \
            'Host github.com' \
            '  IdentityFile /root/.ssh/ww_id_ed25519' \
            '  IdentitiesOnly yes' \
            '  StrictHostKeyChecking yes' \
            > /etc/ssh/ssh_config.d/99-github.conf

COPY .gitconfig /root/.gitconfig
RUN chmod 0600 /root/.gitconfig

ENV GIT_SSH_COMMAND="ssh -i ${SSH_KEY_PATH} ${GIT_SSH_OPTIONS}"

# WORKDIR ${WORKDIR_PATH}
WORKDIR /app
# COPY pyproject.toml pdm.lock ./
COPY . .

# # If you use a private index, inject it as a build secret (no token in image layers)
# RUN --mount=type=secret,id=pip_index_url \
#     export PIP_INDEX_URL="$(cat /run/secrets/pip_index_url)" && \
#     PDM_VENV_IN_PROJECT=1 pdm sync --prod --frozen-lockfile --no-self --no-editable

CMD ["bash", "-l"]
