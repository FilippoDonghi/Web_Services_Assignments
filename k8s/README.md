# Kubernetes example (unsupported)

These manifests are a portable learning example, not evidence of a live or production deployment. They deliberately use one replica for each JSON-backed service because the application only provides in-process locking. A real multi-replica deployment needs an external database.

The example assumes:

- a cluster with a default `StorageClass` for the two claims;
- locally available images named `url-shortener-auth:0.1.0` and `url-shortener-shortener:0.1.0` (or edited image references for your registry);
- `kubectl` with Kustomize support.

Build the images from the repository root and load or push them for your cluster:

```bash
docker build -f auth/Dockerfile -t url-shortener-auth:0.1.0 .
docker build -f shortener/Dockerfile -t url-shortener-shortener:0.1.0 .
```

Create the namespace and a secret without storing its value in Git, then apply the example:

```bash
kubectl apply -f k8s/namespace.yaml
kubectl -n url-shortener create secret generic url-shortener-secrets \
  --from-literal=jwt-secret="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
kubectl apply -k k8s
kubectl -n url-shortener rollout status deployment/auth
kubectl -n url-shortener rollout status deployment/shortener
kubectl -n url-shortener rollout status deployment/nginx
kubectl -n url-shortener port-forward service/nginx 8080:80
```

The API is then available through `http://127.0.0.1:8080`. Deleting the namespace removes every example resource, including its persisted data:

```bash
kubectl delete namespace url-shortener
```
