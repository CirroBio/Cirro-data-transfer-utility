#!/usr/bin/env bash
# Build the deployment image and push it to the public ECR repository Cirro
# pulls from, tagged with the commit it was built from.
#
#     bash scripts/publish_image.sh
#
# Requires the AWS CLI, authenticated as an identity with push access.
set -euo pipefail

REGISTRY=public.ecr.aws
REPOSITORY=cirrobio/data-transfer
# ECR Public's API only exists in us-east-1, whatever the caller's default region.
LOGIN_REGION=us-east-1
# Cirro workspaces are x86_64. A native build on an Apple Silicon Mac pushes an
# arm64 image that starts and immediately dies with "exec format error".
PLATFORM=linux/amd64

cd "$(dirname "$0")/.."

if [ -n "$(git status --porcelain)" ]; then
    echo "Working tree is dirty. The tag would name a commit that does not" >&2
    echo "match the image: backend/ and frontend/ are copied in whole, so" >&2
    echo "uncommitted edits there end up inside it. Commit or stash first." >&2
    exit 1
fi

TAG=$(git rev-parse --short HEAD)
IMAGE="$REGISTRY/$REPOSITORY:$TAG"

aws ecr-public get-login-password --region "$LOGIN_REGION" \
    | docker login --username AWS --password-stdin "$REGISTRY"

docker buildx build --platform "$PLATFORM" --tag "$IMAGE" --push .

echo
echo "Pushed $IMAGE"
echo "A workspace pointing at an older tag keeps using it — there is no update"
echo "API, so moving to this one means recreating the workspace."
