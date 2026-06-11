# 螃蟹鸣潮账号接口记录

本文档记录“螃蟹账号交易网站”中鸣潮账号列表与详情入口的当前确认结果。只记录公开页面与前端正常调用的接口，不包含绕过验证码、破解签名或登录权限的做法。

## 站点信息

- 平台：螃蟹游戏服务网
- PC 站点：https://www.pxb7.com/
- 鸣潮游戏 ID：`10302`
- 鸣潮列表页：https://www.pxb7.com/seo/buy/10302/1
- 前端 API 基址：`https://api-pc.pxb7.com/api`

## 1. 鸣潮账号列表

```http
POST https://api-pc.pxb7.com/api/search/product/v2/selectSearchPageList
```

### 已验证请求体

```json
{
  "query": "",
  "gameId": 10302,
  "pageIndex": 1,
  "pageSize": 20,
  "bizProd": 1,
  "type": "4"
}
```

### 已验证请求头

```http
User-Agent: Mozilla/5.0
Accept: application/json, text/plain, */*
Content-Type: application/json
Origin: https://www.pxb7.com
Referer: https://www.pxb7.com/seo/buy/10302/1
```

### 响应结构

顶层结构：

```json
{
  "success": true,
  "errCode": "00000",
  "errMessage": "成功",
  "data": {
    "properties": {},
    "list": []
  }
}
```

`data.list[]` 中目前可直接获取的关键字段：

| 字段 | 含义 | 用途 |
| --- | --- | --- |
| `productId` | 商品 ID | 详情页与详情接口主键 |
| `productUniqueNo` | 螃蟹商品编号 | 展示与去重辅助 |
| `gameId` / `gameName` | 游戏 ID / 游戏名 | 校验是否为鸣潮 |
| `price` | 价格，单位为分 | 转为元后用于性价比 |
| `showTitle` | 商品标题/资产描述 | 初步解析角色、武器、资源 |
| `attrNameList` | 标签列表 | 区服、TAP、Wegame 绑定状态 |
| `createTime` | 创建时间 | 发布时间 |
| `shelveUpTimeText` | 相对发布时间 | 展示 |
| `pcImgCount` / `h5ImgCount` | 截图数量 | 判断详情素材完整度 |
| `guarantee` | 找回包赔标记 | 风险项 |
| `mainImageUrl` | 主图 | 后续可用于 OCR/截图判断 |

### 分页方式

- `pageIndex`：页码，从 `1` 开始。
- `pageSize`：每页条数。当前已验证 `20` 可用。
- 列表页路径中的最后一段也表示页码，例如 `/seo/buy/10302/1`。

## 2. 商品详情

商品详情页：

```text
https://www.pxb7.com/product/{productId}/1
```

详情 API：

```http
GET https://api-pc.pxb7.com/api/product/web/product/detail?productId={productId}
```

也验证到 `POST /api/product/web/product/detailPost` 使用 `{"productId":"..."}` 可返回同类详情数据，但当前优先使用 GET 详情接口。

### 详情响应中已发现字段

详情 `data` 中可用字段包括：

| 字段 | 含义 |
| --- | --- |
| `productId` | 商品 ID |
| `productUniqueNo` | 螃蟹商品编号 |
| `price` | 价格，单位为分 |
| `showTitle` | 完整标题/账号资产描述 |
| `productAttrs` / `attrs` | 商品属性 |
| `images` | 详情截图 |
| `sellerRemark` | 卖家备注 |
| `guarantee` | 找回包赔 |
| `gameName` / `gameId` | 游戏信息 |
| `shelveUpTime` / `shelveUpTimeText` | 上架时间 |

下一阶段需要随机抽取 `10` 个账号详情，验证能否从这些字段中稳定解析角色、武器、资源、等级、区服和绑定/安全说明。

### 详情解析验证结果

当前 `fetch_detail.py` 已验证：

- 抽样数量：`10`
- 详情请求成功：`10`
- 核心字段解析成功：`10`
- 错误数：`0`

已能解析的标准字段：

| 标准字段 | 来源 |
| --- | --- |
| `price` | `data.price`，单位分转元 |
| `characters` | `data.showTitle` 中的 `N个五星角色：...` |
| `weapons` | `data.showTitle` 中的 `N个五星武器：...` |
| `resources` | `data.reportTitleAttr` 或 `data.showTitle` |
| `level` | `data.reportTitleAttr` 的 `联觉等级` 或标题 |
| `server` | `productAttrs` / `attrs` 中的 `按操作系统` |
| `risk_flags` | TAP、Wegame、换绑 CD、找回包赔、截图来源 |

## 3. 当前结论

第一阶段“数据入口确认”和第二阶段“账号详情抓取”已经具备实现基础：

- 列表页路径明确：`/seo/buy/10302/{page}`。
- 列表 API 明确：`/api/search/product/v2/selectSearchPageList`。
- 详情页路径明确：`/product/{productId}/1`。
- 详情 API 明确：`/api/product/web/product/detail?productId={productId}`。
- 列表中能直接拿到不少于 20 个账号的价格、标题、详情链接、发布时间等基础信息。
- 详情中能稳定解析角色、武器、资源、等级、区服和绑定/安全说明。
