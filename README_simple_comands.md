# Simple Docker Commands

Run these commands from the stack directory (contains `docker-compose.yml`).

## Stop the stack without destroying logs

This stops the containers but keeps them, so Docker logs are preserved.

```bash
docker compose stop
```

## Start the stack again

```bash
docker compose start
```

If the containers do not already exist, use:

```bash
docker compose up -d
```

## Restart the stack without destroying logs

```bash
docker compose restart
```

## Check running containers

```bash
docker compose ps
```

```bash
docker ps
```

## Watch pool payment/share messages

```bash
docker logs -n 10 -f pool 2>&1 | grep "💵"
```

## Watch recent pool logs

```bash
docker logs -n 50 -f pool
```

## Watch node logs

```bash
docker logs -n 50 -f node
```

## Watch dashboard logs

```bash
docker logs -n 50 -f dashboard
```

## Watch postgres logs

```bash
docker logs -n 50 -f postgres
```

## Important: commands to avoid if you want to keep Docker logs

Do not use these unless you are intentionally removing containers/data:

```bash
docker compose down
docker compose rm
docker volume rm ...
docker system prune
```

`down` removes containers, which removes the normal Docker container logs.
