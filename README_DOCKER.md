# Aggregator (Fork) — Docker 部署说明

本 fork 目标：把 `wzdnzd/aggregator` 的 **collect 模式**用 `docker compose` 标准化部署，输出文件落盘，并可选通过 Nginx 对外提供静态订阅文件。

> 说明：本项目用于订阅/代理资源的聚合与转换，请自行遵守当地法律法规与各站点服务条款。

## 1. 快速开始

```bash
# 进入仓库根目录
cp .env.example .env
mkdir -p data

# 构建镜像 + 启动 Nginx 静态服务（可选）
docker compose up -d data-server

# 执行一次采集任务（执行完即退出，产物在 ./data）
docker compose run --rm aggregator
```

产物会出现在 `./data/`，常见文件名：
- `clash.yaml`
- `v2ray.txt`
- `singbox.json`
- `subscribes.txt`
- `valid-domains.txt`

如果你启动了 `data-server`，则可通过：
- `http://<host>:8099/clash.yaml`
- `http://<host>:8099/v2ray.txt`
- `http://<host>:8099/singbox.json`

## 2. 常用命令

```bash
# 查看容器
docker compose ps

# 只启动静态文件服务
docker compose up -d data-server

# 重新执行一次采集
docker compose run --rm aggregator

# 停止服务
docker compose down
```

## 3. 可选：推送到 GitHub Gist

`subscribe/collect.py` 支持通过环境变量配置：
- `GIST_PAT`: GitHub Token
- `GIST_LINK`: `username/gist_id`

把它们写到 `.env` 后，再执行：

```bash
docker compose run --rm aggregator
```

## 4. 权限说明

`./data` 需要容器内可写。最省事的方式：

```bash
chmod 777 data
```

（更严格可用 `chown` 方式，按你的部署用户调整。）
