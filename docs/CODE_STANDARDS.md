# 项目代码规范

本文档整理当前仓库已经采用的代码边界和交付检查，作为新增功能、接口和报告的统一约定。

## 目录职责

| 目录 | 职责 | 约定 |
| --- | --- | --- |
| `ladle_preallocation/` | 当前运行时 Python 包 | 新业务逻辑、输入适配器、决策树、LLM Workflow 和响应控制器放这里。 |
| `backend/ladle_preallocation/` | 历史整理后的镜像目录 | 不在这里单独实现新逻辑；如需迁移必须先统一导入路径并增加同步验证。 |
| `tools/` | CLI、报告生成和本地 HTTP 服务 | 脚本负责组装入口，业务规则放到包内纯函数。 |
| `tests/` | 自动化测试 | 一个测试文件对应一个模块或跨层契约，优先测试公开行为。 |
| `docs/` | API、产品和设计文档 | OpenAPI 以 `tools/serve_visualization.py` 的实际路由为事实来源。 |
| `data/` | 输入数据和样例 | 生产数据不写入代码、日志或 API 响应。 |
| `outputs/` | 生成产物和审计结果 | 由脚本生成，禁止手工修改生成文件来修复逻辑。 |

## Python 约定

- 使用 Python 3.10+ 语法，4 个空格缩进；文件顶部保留 `from __future__ import annotations`（项目现有模块已采用时保持一致）。
- 导入顺序为标准库、第三方库、本项目模块；项目模块使用绝对导入 `ladle_preallocation...`。
- 公共函数和类必须有简短 docstring；边界函数必须标注输入和返回类型。
- 纯数据转换、校验和响应组装优先使用独立函数，HTTP handler 只负责路由、读取请求和写响应。
- 不复制决策树的约束或评分逻辑；统一调用 `allocate()`、`validate_output()` 和共享控制器。
- 配置通过 `.env.local` `source` 后进入进程环境；代码、测试、审计和响应不得写入 `LLM_API_KEY`。

## API 约定

- 新增 HTTP 路由必须同时更新 `docs/ladle-preallocation-openapi.yaml`、接口测试和 README 的调用示例。
- 请求模型使用 `Input...` 命名，响应模型使用 `Output...` 命名；时间字段使用 RFC 3339/date-time。
- `400` 表示 JSON、类型或必填字段错误；`404` 表示资源不存在；`409` 表示资源快照冲突；`422` 表示请求可解析但业务约束无法完成；`500/503` 表示服务或依赖不可用。
- 错误响应使用 JSON 对象，至少包含 `error`；需要定位时加入 `error_type`、`request_id` 或 `details`，不要回显完整请求体。
- 正常预配包使用决策树；LLM 只能在扰动 Workflow 中作为候选方案生成器，并且必须经过硬约束校验。

## 日志和安全

- 使用模块级 `logging.getLogger(__name__)`；正常路径不打印请求体、prompt、Authorization 或密钥。
- 异常日志记录异常类型和本地上下文，客户端响应使用稳定的中文错误信息，避免暴露堆栈和内部路径。
- 审计只记录来源、算法版本、资源数量、状态和校验摘要；禁止写入 LLM 密钥、完整环境变量和完整认证头。
- 离线受控事故必须标记为受控注入，不得描述成真实生产事故或外部 API 调用。

## 测试与交付门槛

提交前至少执行：

```bash
.venv/bin/python -m pytest -q tests
.venv/bin/python -m py_compile ladle_preallocation/**/*.py tools/*.py
git diff --check
```

修改 HTTP 契约时还要验证：

- OpenAPI 能被 YAML 解析器读取，所有 `$ref` 都指向已定义的组件；
- 成功、参数错误、资源冲突、业务不可行和旧接口兼容路径都有测试；
- README、OpenAPI 和服务实际路由的路径、字段名称、状态码一致。

## 禁止事项

- 不要在正常预配包接口中实例化或调用 LLM。
- 不要把未经 `validate_output()` 或场景校验的 LLM 分配结果直接当作可下发指令。
- 不要在工具脚本中复制业务算法，也不要在 `backend/` 镜像中创建与运行时包分叉的新实现。
- 不要提交 `.env.local`、生产 Excel、临时数据库、Python 缓存或未审计的生成产物。
