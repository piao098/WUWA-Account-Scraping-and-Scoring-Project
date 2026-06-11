# 鸣潮账号标准数据结构

本文档定义螃蟹鸣潮账号评估器的标准账号 JSON。抓取脚本可以保留原始字段，但评分、排序、报告只应依赖这里定义的稳定字段。

## Account

```json
{
  "account_id": "2221526477374442510",
  "product_unique_no": "MBMVP7507",
  "game_id": "10302",
  "game_name": "鸣潮",
  "title": "80级，61黄...",
  "price": 1280.0,
  "price_cent": 128000,
  "detail_url": "https://www.pxb7.com/product/2221526477374442510/1",
  "published_at": "2026-06-11 01:11:15",
  "published_text": "12分钟内发布",
  "level": 80,
  "yellow_count": 61,
  "five_star_character_count": 25,
  "five_star_weapon_count": 21,
  "characters": [],
  "weapons": [],
  "resources": {},
  "server": "官服",
  "risk_flags": {},
  "security": {},
  "main_important_keys": [],
  "image_count": 3,
  "images": [],
  "seller_remark": null,
  "raw_attrs": {},
  "raw": {}
}
```

## Core Fields

以下字段是评分链路的核心字段，缺失率必须控制在 `20%` 以内。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `account_id` | string | 商品 ID，主键 |
| `price` | number | 价格，单位元 |
| `title` | string | 账号资产描述 |
| `detail_url` | string | 详情页链接 |
| `level` | number | 联觉等级 |
| `server` | string | 官服、国际服、B 服等 |
| `characters` | array | 五星角色列表 |
| `weapons` | array | 五星武器列表 |
| `resources` | object | 星声、月相、余波珊瑚、浮金波纹、铸潮波纹 |
| `risk_flags` | object | 绑定、换绑、包赔、截图来源等风险项 |

## Character

```json
{
  "name": "维里奈",
  "resonance": 3
}
```

- `name`：角色名。
- `resonance`：共鸣链，`0-6`；标题中的 `满命` 统一记为 `6`。

## Weapon

```json
{
  "name": "千古洑流",
  "refinement": 1
}
```

- `name`：武器名。
- `refinement`：精炼等级；未解析到时为 `null`。

## Resources

```json
{
  "星声": 47005,
  "月相": 3234,
  "余波珊瑚": 496,
  "浮金波纹": 7,
  "铸潮波纹": 28
}
```

资源字段可以缺少单项，但至少需要有一项可解析资源，否则该账号不满足详情核心字段要求。

## Risk Flags

```json
{
  "tap_binding": "未绑定TAP",
  "wegame_binding": "未绑Wegame",
  "change_bind_cd": "无换绑CD",
  "guarantee": true,
  "screenshot_source": "官方截图"
}
```

评分阶段会根据风险项扣分，例如已绑定平台、存在换绑 CD、自主截图、缺少找回包赔等。

