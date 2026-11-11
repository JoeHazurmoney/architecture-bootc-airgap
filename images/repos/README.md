# Internal package repositories (airgap)

Put `*.repo` files here that point at your internal mirrors (Satellite, Pulp,
or a `reposync` mirror on the HTTP server). If any `*.repo` file is here, the
image builds use **only** these repos (`--setopt=reposdir=/run/extra-repos`).

If this directory is empty, the build uses whatever repos the base image and
build host provide. On a subscribed RHEL build host, that means the
entitlements podman injects automatically.

`*.repo` files are git-ignored so internal hostnames don't leak into the repo.
