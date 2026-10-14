# LDPartsScanner — LDTools 主机配件拍照录入 APK

配合 LDTools 服务端（LDTH5）使用的安卓 APP：操作者用手机对 CPU / 主机拍照，
端上 OCR 自动识别关键参数，人工确认后一键上传到 LDTools 服务器，
网页端「主机配件查询」（`http://<服务器>:9876/parts.html`）即可查看档案与照片留档。

## 功能

| 功能 | 实现 |
| --- | --- |
| CPU 照片识别 | ML Kit Text Recognition（拉丁引擎，端上离线） |
| 主机标签识别 | ML Kit Text Recognition（中文引擎，识别「出厂编号/批号/型号」） |
| 条形码 / 二维码 | ML Kit Barcode 实时扫码 → 填主机编号 |
| 拍照 | CameraX（后置、高质量模式、手电筒） |
| 确认后上传 | OkHttp multipart → `POST /api/parts-archive` |
| 留档 | 服务端 `Parts_Archive/PA_<时间>_<SN>/`（原图 + meta.json + index.json） |

自动识别字段（识别后均可手动修改）：

- **CPU 型号**：如 `I7-14700`（兼容 OCR 把 I 认成 l/1、全角破折号等）
- **CPU 批号**：如 `L510G664`（Intel FPO：字母+3数字+字母+3数字）
- **CPU 编号**：如 `01652`（基板边缘 5 位 ATPO，给候选列表点击填入）
- **主机编号**：如 `YLX5BZZB`（标签「出厂编号」，扫码优先）
- 主机批号 / 主机型号：识别后自动追加到备注

## 构建 APK

1. 安装 Android Studio（Hedgehog 及以上，自带 JDK 17）。
2. `File → Open` 打开本目录（`apk/LDPartsScanner`），首次 Sync 会按
   `gradle/wrapper/gradle-wrapper.properties` 自动下载 Gradle 8.7 与依赖
   （ML Kit 模型随 Play Services 或内嵌到 APK，国内网络建议给 Android Studio 配代理或镜像）。
3. `Build → Build App(s) / Build APK(s)` 生成
   `app/build/outputs/apk/debug/app-debug.apk`，传到手机安装。

命令行构建（需本机有 JDK 17 + Android SDK，并先创建 local.properties 写 sdk.dir）：

```bat
gradlew.bat assembleDebug     :: 首次会提示缺少 wrapper jar，可用 Android Studio 打开一次自动生成
```

> 说明：仓库内只包含 `gradle-wrapper.properties`（不含二进制 wrapper jar），
> 用 Android Studio 打开是最简单的方式；命令行构建前先 `gradle wrapper` 生成 jar。

## 使用流程

1. 首次打开 → 底部「服务器设置」填服务器地址（如 `192.168.1.100:9876`，可省略 http://）
   和访问密码（与网页登录密码一致）→ 保存。
2. 拍 **CPU 照**（对准丝印文字，含型号/批号/边缘编号）→ 自动识别填表，编号候选点击选择。
3. 拍 **主机照**（对准整机标签）→ 自动识别出厂编号；或点「扫码」扫主机条码/二维码。
4. 点「确认并上传」→ 弹窗核对信息 → 确认 → 上传（显示进度）。
   - **历史档案永不覆盖**：每次上传完整新增一条记录（同一 CPU/主机重复出现时各条独立保留）。
   - 若该 CPU（**型号+批号+编号三者一致**才认定为同一颗）已录入过，确认弹窗会提示它曾出现在哪些主机及时间，
     方便当场发现 CPU 复用/串号等异常；网页档案列表也会给这类记录打「⚠ CPU 重复」徽章。
5. 电脑浏览器打开 `http://<服务器>:9876/parts.html`（或主页面头部「主机配件查询」入口）
   查看/搜索/删除档案，点击缩略图看原图。

## 服务端 API（LDTH5 server.py，均需鉴权）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/parts-archive` | 全量记录列表 |
| GET | `/api/parts-archive?folder=PA_xxx` | 单条明细（含图片 URL） |
| POST | `/api/parts-archive` | multipart 上传（`sn` 必填 + `cpuModel/cpuBatch/cpuCode/note` + `cpuFile*/hostFile*` 各最多 6 张） |
| DELETE | `/api/parts-archive?folder=PA_xxx` | 永久删除 |
| GET | `/api/parts-image?path=PA_xxx/cpu_1.jpg&token=...` | 图片下载（`<img>` 直连用） |

鉴权：`Authorization: Bearer <token>`，token 由 `POST /api/auth`（访问密码）获取，8 小时有效，过期自动重登。

## 常见问题

- **识别不准**：保持文字与镜头平行、离近一点、开手电筒补光；识别失败可手动输入后再拍一张复核。
- **上传失败提示网络错误**：手机与服务器必须在同一局域网，且服务器防火墙放行 9876 端口。
- **登录已过期**：token 8 小时失效，APP 会在下次上传时自动用保存的密码重新登录。
- **机型较老**：ML Kit 文本识别需 Google Play Services（或使用内嵌模型），Android 7.0 以上可用。
