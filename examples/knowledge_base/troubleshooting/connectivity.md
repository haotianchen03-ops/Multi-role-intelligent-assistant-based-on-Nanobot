# 连接问题排查

---

## 网络连接检查

### 步骤1: 测试基本连通性

```bash
# 测试能否访问我们的服务器
ping api.example.com

# 测试特定端口
telnet api.example.com 443
```

### 步骤2: 检查代理设置

如果使用代理，确保以下域名在白名单中：
- `api.example.com`
- `auth.example.com`
- `cdn.example.com`

### 步骤3: 检查防火墙

确保 outbound 规则允许：
- HTTPS (443)
- WebSocket (443)

---

## 常见连接错误

### 连接被拒绝

**错误信息**: `ECONNREFUSED`

**解决方案**:
1. 确认 API 地址正确
2. 检查端口是否正确（默认443）
3. 确认服务器正常运行

### SSL 证书错误

**错误信息**: `UNABLE_TO_VERIFY_LEAF_SIGNATURE`

**解决方案**:
1. 更新本地 CA 证书
2. 确认时间设置正确
3. 某些代理软件可能需要禁用 SSL 验证（不推荐）

### DNS 解析失败

**错误信息**: `ENOTFOUND`

**解决方案**:
1. 检查网络连接
2. 尝试使用 8.8.8.8 作为备用 DNS
3. 直接使用 IP 而非域名访问