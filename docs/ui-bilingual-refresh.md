# Wiki 界面与双语

本次界面更新使用 Linked N 标识，缩短首页介绍与 TodoList 推广，让项目和资源先出现。内容卡片采用明确边框和轻阴影；项目列表展示分类、年份、负责人和两行简介，完整成员信息仍在详情页。

## 偏好与显示

- 页头 EN / 中文即时切换语言，不刷新页面；搜索、筛选和未提交表单保留。
- `nethub-language` 保存 `zh` / `en`，默认中文；`nethub-theme` 默认 `system`，手动切换后保存 `light` / `dark`。存储不可用时当前页面仍可使用。
- localStorage 按站点 origin 隔离。两个产品使用相同键名，但不跨域读取彼此的偏好。
- 时间仍使用北京时间；首页通知使用固定 `MM-DD` 日期，切换语言与刷新时顺序一致。

## 文本边界

`translations.js` 与 `translations-static.js` 只包含开发者编写的界面文案。`i18n.js` 在 API 页面脚本之前标记初始静态界面；动态 HTML 使用 `ui` 模板标签，只翻译字面片段，插值内容保持不透明。

项目名、简介、评论、成员姓名和用户输入不进行自动翻译。内置分类有明确白名单；自定义分类保持原文。带插值的 aria-label/title 分别保存字面片段与原值，切换时通过 setAttribute 更新，不再次解析用户 HTML。

新增界面文本时，将翻译加入词典：

- HTML 模板使用 `ui` 标签；用户插值仍须遵守已有 `escapeHtml` 规则。
- 普通界面字符串使用 `tr`，带插值的普通文本使用 `ut` 标签。
- 需要即时更新的 textContent 使用 `setUiText(node, () => ...)`；这不会覆盖后来被业务代码清空或替换的状态。
- 表单 value、URL、数据枚举和接口参数保持原值。不要扫描 API 返回内容做整页翻译。

## 验证

使用 conda 环境 `nethub_campus_wiki`：

```text
python -m pytest tests/test_frontend_server.py tests/test_project_assets.py tests/test_resource_thumbnails.py -q
node tests/test_frontend_i18n.cjs
node tests/test_frontend_time.cjs
node tests/test_messages_scroll.js
```

本地化检查覆盖用户内容隔离、动态属性和属性展开、表单原值、语言保存、动态标题、已清空状态及页面加载顺序。预览中进行中英/主题切换、搜索、分类和资源导航的浏览器检查；真实登录后的管理写入操作不属于这次只读预览的验证范围。
