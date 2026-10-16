package com.ldtools.parts;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * OCR 文本解析器 — 从 ML Kit 识别出的文本行里提取：
 *
 * CPU 照片（Intel/AMD 处理器基板丝印）：
 *   - CPU 型号   如 I7-14700 / ULTRA 7 265 / RYZEN 7 5800X
 *               （"INTEL(R) CORE(TM) I7" 下一行 "i7-14700"；
 *                [v1.10] Intel Core Ultra 顶盖型号数字单独一行（"CORE ULTRA 7" ↓ "265"）跨行拼接，
 *                并支持 AMD Ryzen 主流系列（RYZEN 7 5800X 等，同行/分行均可））
 *   - CPU 批号   如 L510G664        （FPO，格式：字母+3数字+字母+3数字，新 CPU V610G688 同格式）
 *   - CPU 编号   如 01627           （ATPO，基板边缘 5 位数字，给出候选列表；Ultra 系列同为数字）
 *
 * 主机照片（整机标签）：
 *   - 主机编号   如 YLX5BZZB        （"出厂编号: YLX5BZZB"，也兼容 S/N、SN）
 *   - 主机批号   如 YLN0SS505W0A    （"批号: ..."，写入备注）
 *   - 主机型号   如 ThinkCentre M770e MEL2
 *               [v1.03] 按原始大小写整行完整匹配（不再强制大写/截断），独立填入型号框
 *               [v1.07] 标签写法全支持：型号/型號/机型/型号名称/MODEL/MODE/MACHINE TYPE，
 *                       无标签时品牌系列大字行（ThinkCentre M770e 等）兜底
 *               [v1.12] 标签值断行补全：「产品型号：Vostro」↓「3020 SFF」→ Vostro 3020 SFF
 * [v1.12] 内存/固态完整参数 + 多根数量：
 *   内存 如 "SAMSUNG 8GB DDR4 3200MHz x2 | SN:… | SN:…"
 *         （品牌词表 + PN 前缀推断 M378…=三星/MTA…=美光；PC4 统一表达 DDR4；同 PN 重复/不同 SN 数 → xN）
 *   固态 如 "SAMSUNG 1TB NVMe x2 | SN:…"
 * [v1.19] 按 31 份档案实拍照片校准（三星/海力士/美光/铠侠/东芝/群联/UM/联想/Dell 标签布局）：
 *   内存：海力士竖排小标签「SN: 标签独占一行」跨行拾取值；80CE/80AD 无标签独立长串行直接认 SN
 *   固态：群联裸容量（NVME/SSD 行内 256/512/960 无 GB 后缀）；MTFDK 前缀 → MICRON；
 *         机械盘（东芝等 HDD/7200RPM 字样）输出 "SATA HDD" 与固态区分
 *   主机：联想无 S/N 字样时从条码行「(1S)13ASCT01WW GM1GB370」末段取出厂编号
 */
public final class OcrParser {

    /** CPU 照片解析结果 */
    public static class CpuResult {
        public String model;                       // I7-14700 / ULTRA 7 265 / RYZEN 7 5800X
        public String batch;                       // L510G664（FPO）
        public final List<String> codeCandidates = new ArrayList<>();  // ATPO 候选（5 位数字），按置信度降序
    }

    /** 主机照片解析结果 */
    public static class HostResult {
        public String sn;                          // 出厂编号（第一候选）
        public String batch;                       // 批号
        public String machineModel;                // 整机型号（第一候选）
        /** 主机编号候选（S/N、SN、S/T、ST、出厂编号等标签后面的值，去重，最多 5 个） */
        public final List<String> snCandidates = new ArrayList<>();
        /** [v1.02] 主机型号候选（"型号:" 标签后的值，去重，最多 5 个） */
        public final List<String> machineModelCandidates = new ArrayList<>();
    }

    // CPU 型号（Intel Core i3-i9）：兼容 OCR 把 I 认成 l/1、破折号变体、缺连字符等
    // （i7 14700 / I7—14700 / l7-14700）
    private static final Pattern RE_MODEL = Pattern.compile(
            "(?:CORE)?\\s*[Il1]([3579])\\s*[-]?\\s*(\\d{4,5})([A-Z]{0,2})");
    // [v1.10] Intel Core Ultra 同行格式：CORE ULTRA 7 265 / ULTRA 5 245K / ULTRA 7 155H
    // （Arrow Lake / Meteor Lake / Lunar Lake 系列，型号 3 位数字 + 可选后缀 K/KF/H/HX/V…）
    private static final Pattern RE_ULTRA = Pattern.compile(
            "ULTRA\\s*([3579])\\s+(\\d{3}[A-Z]{0,2})(?![A-Z])");
    // [v1.10] AMD Ryzen 同行格式：RYZEN 7 5800X / RYZEN 5 5600 / RYZEN 9 7950X3D
    private static final Pattern RE_AMD = Pattern.compile(
            "RYZEN\\s*(?:\\(TM\\)|TM|™)?\\s*([3579])\\s*[- ]?\\s*(\\d{4}[A-Z0-9]{0,4})(?![A-Z0-9])");
    // [v1.10] 跨行系列行（型号数字在下一行，如新 CPU 顶盖 "INTEL CORE ULTRA 7" ↓ "265"）
    private static final Pattern RE_SERIES_LINE = Pattern.compile(
            "(ULTRA|RYZEN\\s*(?:\\(TM\\)|TM|™)?)\\s*([3579])\\s*$");
    // [v1.10] 跨行型号片段（独立一行）："265" / "155H" / "5800X" / "7950X3D"；
    // 刻意不匹配 5 位纯数字（那是 ATPO 编号），4 位无后缀也认（"5600"）
    private static final Pattern RE_MODEL_FRAGMENT = Pattern.compile(
            "^(?:\\d{3}[A-Z]{0,2}|\\d{4}(?:[A-Z][A-Z0-9]{0,3})?)$");
    // FPO 批号：字母+3数字+字母+3数字（L510G664 / X329B555），前后不能是字母数字（防吞进长串）
    private static final Pattern RE_FPO = Pattern.compile(
            "(?<![A-Z0-9])([A-Z]\\d{3}[A-Z]\\d{3})(?![A-Z0-9])");
    // ATPO：独立的 5 位数字
    private static final Pattern RE_ATPO = Pattern.compile("(?<!\\d)(\\d{5})(?!\\d)");
    // [v1.09] 主机出厂编号标签：出厂编号/序列号/编号（联想）/S/N/SN/S/T/ST（ST=Service Tag，Dell 服务编号）/
    // 服务编号/服务代码/快速服务代码/SVC TAG/SERVICE TAG/EXPRESS CODE（Dell）。
    // 标签前不能是字母（防 HOST: 里的 ST 误命中）；值放宽为字母或数字开头（快速服务代码是纯数字）
    private static final Pattern RE_HOST_SN = Pattern.compile(
            "(?<![A-Z])(?:出厂编号|序列号|快速服务代码|服务编号|服务代码|编号"
                    + "|S/?[NT]|SVC\\s*TAG|SERVICE\\s*TAG|EXPRESS\\s*(?:SERVICE\\s*)?CODE)"
                    + "\\s*[:]?\\s*([A-Z0-9][A-Z0-9-]{4,19})");
    // 主机批号
    private static final Pattern RE_HOST_BATCH = Pattern.compile(
            "批\\s*号\\s*[:]?\\s*([A-Z][A-Z0-9-]{5,23})");
    // [v1.19] 联想条码行：「(1S)13ASCT01WW GM1GB370」——末段 7-8 位字母数字是出厂编号
    // （标签没有 S/N 字样时；ThinkCentre/扬天/启天包装标签统一格式）
    private static final Pattern RE_LENOVO_SN_BAR = Pattern.compile(
            "\\(1S\\)[A-Z0-9]{6,12}\\s+([A-Z0-9]{7,8})(?![A-Z0-9])");
    // [v1.07] 整机型号：逐行在原始文本上匹配（保留原样大小写，如 ThinkCentre M770e MEL2），
    // 标签写法全支持：型号 / 型號 / 机型 / 型号名称 / MODEL / MODE / MACHINE TYPE，
    // 冒号可省略，值按标签原样整行取全（含空格），不再截断在第一个空格
    private static final Pattern RE_MACHINE_MODEL = Pattern.compile(
            "(?:型\\s*号(?:\\s*名\\s*称)?|型\\s*號|机\\s*型|\\bMODEL\\b|\\bMODE\\b|\\bMACHINE\\s*TYPE\\b)"
                    + "\\s*[:：]?\\s*(\\S.*)",
            Pattern.CASE_INSENSITIVE);
    // [v1.07] 型号值尾部截断：粘连的下一字段标签（中文+英文）/ 网址等
    private static final Pattern RE_MODEL_TAIL_CUT = Pattern.compile(
            "批\\s*号|出厂编号|序列号|日\\s*期|生产日期|https?://|www\\."
                    + "|\\bMODEL\\b|\\bMODE\\b|\\bMACHINE\\s*TYPE\\b"
                    + "|\\bS\\s*/?\\s*N\\b\\s*[:：]|\\bP\\s*/?\\s*N\\b\\s*[:：]",
            Pattern.CASE_INSENSITIVE);
    // [v1.07] 兜底：标签上没有「型号/MODEL」字样时，主机品牌系列大字行（如 ThinkCentre M770e）也当候选
    private static final Pattern RE_MACHINE_BRAND_LINE = Pattern.compile(
            "^(?:Lenovo\\s+|Dell\\s+|HP\\s+|联想\\s*)?(?:Think(?:Centre|Station|Pad)|OptiPlex"
                    + "|Elite(?:Desk|Book)|Pro(?:Desk|Book)|Vostro|Inspiron|Precision"
                    + "|Pavilion|ExpertCenter|Chromebox)\\s+\\S+.*",
            Pattern.CASE_INSENSITIVE);
    // [v1.09] 主机品牌词：标签只印品牌没印具体型号时（如「中小企业商用台式机Vostro」），
    // 把品牌词填入型号框让用户补全（中文系列名不受 normalize 大写影响）
    private static final String[] MACHINE_BRANDS = {
            "ThinkCentre", "ThinkStation", "ThinkPad", "OptiPlex", "Latitude", "Precision",
            "Vostro", "Inspiron", "EliteDesk", "EliteBook", "ProDesk", "ProBook",
            "Pavilion", "ExpertCenter", "Chromebox", "Lecoo", "天逸", "扬天", "启天"};
    // [v1.13] 联想 Tiny 小主机型号（标签上没有 ThinkCentre 字样）：
    // 如 "P3 Tiny Gen 2 (1SWMT - M30KG - S4HP00" → 主型号 "P3 Tiny Gen 2"（M720q/M90q 等同格式）
    private static final Pattern RE_TINY_MODEL = Pattern.compile(
            "\\b([A-Z]\\d{1,3})\\s+Tiny(?:\\s+Gen\\s*(\\d))?\\b",
            Pattern.CASE_INSENSITIVE);
    // 通用配件标签关键词：内存（DDR/GB/MHz）/ 固态（SSD/M.2/NVMe/TB）
    private static final Pattern GENERIC_KEYWORDS = Pattern.compile(
            "DDR\\d|LPDDR|GB|TB|MHZ|MT/S|PC[34]|SODIMM|U_DIMM|SSD|M\\.2|NVME|PCIE|SATA|"
            + "WIFI|WLAN|AX\\d{3,3}|AC\\d{3,3}|GBE|以太网|ETH|RTL\\d|I2\\d{3}-V|Bcm|INTEL.*NETWORK|REALTEK");
    // [v1.04] 内存：容量 / 代数(PC4/PC5/DDR4/DDR5/LPDDR) / 频率 / PN·SN 序列号
    // [v1.07] 频率分隔符加 \s：OCR 常把 "PC4-3200AA" 断成 "PC4 -3200AA"
    private static final Pattern RE_RAM_CAP  = Pattern.compile("(?<!\\d)(\\d{1,3})\\s?GB(?![A-Z])");
    private static final Pattern RE_RAM_TYPE = Pattern.compile("(LPDDR\\d|DDR\\d|PC[45])(?:[-\\s]?(\\d{4,5}))?");
    private static final Pattern RE_SERIAL   = Pattern.compile(
            "(?<![A-Z])(S/?N|P/?N)\\s*[:：]?\\s*([A-Z0-9][A-Z0-9-]{3,19})(?![A-Z0-9])");
    // [v1.04] 固态硬盘：品牌词表 [v1.07] 增补国产主流品牌 [v1.13] 加 UNION MEMORY（联想 UM）
    private static final String[] SSD_BRANDS = {
            "SAMSUNG", "三星", "SK HYNIX", "海力士", "WESTERN DIGITAL", "WD", "西部数据", "SANDISK", "闪迪",
            "KINGSTON", "金士顿", "CRUCIAL", "英睿达", "MICRON", "镁光", "KIOXIA", "铠侠",
            "INTEL", "SEAGATE", "希捷", "TOSHIBA", "东芝", "ADATA", "威刚", "HP",
            "DELL", "LENOVO", "联想", "HUAWEI", "宏碁", "ACER", "GIGABYTE", "PLEXTOR", "浦科特",
            "HIKSEMI", "海康威视", "COLORFUL", "七彩虹", "GALAX", "影驰", "MAXSUN", "铭瑄",
            "FANXIANG", "梵想", "AIGO", "爱国者", "TIGO", "金泰克", "NETAC", "朗科",
            "TECLAST", "台电", "TRANSCEND", "创见", "LEXAR", "雷克沙", "UNION MEMORY",
            "PHISON", "群联", "LITEON", "LITE-ON", "建兴", "SSSTC", "YMTC", "长江存储",
            "致态", "MAXIO", "联芸"};
    // [v1.13] Union Memory（联想 UM）固态 PN：如 UM3017 512GB（标签只印 UM+数字，无品牌全称）
    private static final Pattern RE_UM_SSD_PN = Pattern.compile("\\bUM\\d{3,4}\\b");
    // [v1.07] 内存：品牌词表（词表按具体度降序，"SK HYNIX" 须在 "HYNIX" 前）
    private static final String[] RAM_BRANDS = {
            "SAMSUNG", "三星", "SK HYNIX", "HYNIX", "海力士", "KINGSTON", "金士顿",
            "CRUCIAL", "英睿达", "MICRON", "镁光", "ADATA", "威刚", "G.SKILL", "芝奇",
            "CORSAIR", "海盗船", "TEAMGROUP", "十铨", "RAMAXEL", "记忆科技",
            "KINGBANK", "金百达", "CUSO", "酷兽", "JUHOR", "玖合", "GLOWAY", "光威",
            "KLEVV", "科赋", "APACER", "宇瞻", "TRANSCEND", "创见", "PATRIOT", "博帝",
            "LEXAR", "雷克沙", "HUAWEI", "LENOVO", "联想", "HP", "DELL", "UNION MEMORY"};
    // [v1.12] 内存 PN 前缀 → 品牌推断（标签只印零件号不印品牌字样时用，
    // 如 M378A1G44CB0-CWE = 三星 8G DDR4、MTA8ATF1G64AZ = 美光）
    private static final String[][] RAM_PN_PREFIXES = {
            {"M378", "SAMSUNG"}, {"M471", "SAMSUNG"}, {"M393", "SAMSUNG"},
            {"HMA", "SK HYNIX"}, {"MTA", "MICRON"}};
    // [v1.12] 内存 PN 完整串（计数用：同一 PN 完整出现 N 次 = 同款 N 根 → xN）
    private static final Pattern RE_RAM_PN = Pattern.compile(
            "\\b(?:M378|M471|M393|HMA|MTA)[A-Z0-9]{4,}(?:-[A-Z0-9]{2,5})?");
    // [v1.07] 固态容量正则（从方法内提取为静态，避免重复编译）
    private static final Pattern RE_SSD_CAP = Pattern.compile(
            "(?<!\\d)(\\d{1,4}(?:\\.\\d)?\\s?(GB|TB))(?![A-Z])");
    // [v1.19] 海力士内存标签（竖排小标签，与三星布局不同）：
    //   "SN:" 标签独占一行（冒号后被换行截断），纯 SN 值在下一行——行级 SN 匹配会漏，需跨行拾取
    private static final Pattern RE_RAM_SN_BARE = Pattern.compile("^SN\\s*:?\\s*$");
    //   [v1.19] 无标签独立 SN 行：80CE/80AD 开头的长序列（三星/海力士 DDR5 UDIMM 序列号规律，
    //   如 80CE01231804AAB817 / 80AD012220554124EF）——标签上没印 SN: 字样
    private static final Pattern RE_RAM_SN_BARE_VAL = Pattern.compile(
            "^80[AC][DE][A-Z0-9]{9,19}$");
    // [v1.19] 固态裸容量：群联等标签只印 "P0327 NVME 512" 会漏掉 GB 后缀场景——
    // 行内已有 NVME/SSD 关键词时，256/480/512/960/1000/1024 裸数字按 GB 认
    private static final Pattern RE_SSD_BARE_CAP = Pattern.compile(
            "(?<![A-Z0-9])(256|480|512|960|1000|1024)(?![A-Z0-9])");
    // [v1.20] 内存频率兜底：标签规格行被 ML Kit 拆成两行（"16GB 1Rx8 PC5" ↓ "-5600B-SA0.00"）
    // 跨行拼接没补上时，搜主流 DDR 频率值（5600B/4800B 的 B 是真实规格后缀非噪声）
    private static final Pattern RE_RAM_FREQ_BARE = Pattern.compile(
            "(?<![A-Z0-9])(2133|2400|2666|2933|3200|3600|4266|4400|4800|5200|5600|6000|6400|6800|7200)B?(?![A-Z0-9])");

    private OcrParser() {}

    /** 统一全角/OCR 常见混淆字符，转大写 */
    public static String normalize(String s) {
        if (s == null) return "";
        return s.replace('：', ':')
                .replace('—', '-')
                .replace('–', '-')
                .replace('－', '-')
                .toUpperCase(Locale.US);
    }

    /** 解析 CPU 照片 OCR 文本行 */
    public static CpuResult parseCpu(List<String> lines) {
        CpuResult r = new CpuResult();
        List<String> norm = new ArrayList<>();
        for (String raw : lines) {
            String line = normalize(raw);
            norm.add(line);
            if (r.model == null) {
                String model = matchModel(line);
                if (model != null) r.model = model;
            }
            if (r.batch == null) {
                Matcher m = RE_FPO.matcher(line);
                if (m.find()) r.batch = m.group(1);
            }
        }
        // [v1.10] 跨行型号补全：系列行（"INTEL CORE ULTRA 7" / "AMD RYZEN 5"）的下一行若是
        // 纯型号片段（"265" / "155H" / "5800X"），拼成完整型号——新 CPU 顶盖的型号数字单独一行
        if (r.model == null) {
            for (int i = 0; i + 1 < norm.size(); i++) {
                Matcher s = RE_SERIES_LINE.matcher(norm.get(i).trim());
                if (!s.find()) continue;
                String frag = norm.get(i + 1).trim();
                if (!RE_MODEL_FRAGMENT.matcher(frag).matches()) continue;
                String prefix = s.group(1).contains("RYZEN") ? "RYZEN" : "ULTRA";
                r.model = prefix + " " + s.group(2) + " " + frag;
                break;
            }
        }
        r.codeCandidates.addAll(rankAtpo(norm));
        return r;
    }

    /**
     * 通用配件标签解析（内存/固态/网卡/其他）：返回候选信息行。
     * 规则：含关键词（DDR/GB/TB/MHz/M.2/NVMe/SSD/WIFI/AX/AC 系列网卡/GbE 等）优先，
     * 必须字母数字混合、长度 3~60，去重后最多 6 个候选。
     */
    public static List<String> parseGeneric(List<String> lines) {
        List<String> hits = new ArrayList<>();
        List<String> rest = new ArrayList<>();
        for (String raw : lines) {
            String line = normalize(raw).trim();
            if (line.length() < 3 || line.length() > 60) continue;
            boolean hasLetter = false, hasDigit = false;
            for (char c : line.toCharArray()) {
                if (Character.isLetter(c)) hasLetter = true;
                else if (Character.isDigit(c)) hasDigit = true;
            }
            if (!hasLetter || !hasDigit) continue;          // 纯数字/纯字母行不要
            if (line.matches("[A-Z0-9 .,:;/|_-]+") && !line.matches(".*[A-Z]{3,}.*")) continue; // 无实质词的行
            if (GENERIC_KEYWORDS.matcher(line).find()) {
                if (!hits.contains(line)) hits.add(line);
            } else {
                if (!rest.contains(line)) rest.add(line);
            }
        }
        // 关键词行不够 4 个时补上其余紧凑行（可能是型号串）
        for (String s : rest) {
            if (hits.size() >= 6) break;
            if (s.length() <= 40 && !hits.contains(s)) hits.add(s);
        }
        return hits.size() > 6 ? new ArrayList<>(hits.subList(0, 6)) : hits;
    }

    /**
     * [v1.04] 内存标签解析 → 摘要行，如：
     *   "SAMSUNG 8GB DDR4 3200MHz x2 | SN:04534C21 | SN:04534C27"
     *   "8GB DDR4-3200 | PN:KHX3200C16D4 | SN:12345678"
     * [v1.12] 品牌（词表 + PN 前缀推断，M378…=三星）+ 容量 + 代数（PC4 统一表达为 DDR4）
     *   + 频率（选填）+ 数量（同 PN 完整串重复次数 / 不同 SN 数，≥2 标 xN）。
     * 拼不出任何要素时返回 null（调用方回落到通用候选）。
     */
    public static String parseRam(List<String> lines) {
        String brand = null, cap = null, typeFreq = null;
        int count = 1;
        java.util.LinkedHashMap<String, String> serials = new java.util.LinkedHashMap<>();
        java.util.LinkedHashMap<String, Integer> pnCount = new java.util.LinkedHashMap<>();
        for (String raw : lines) {
            String line = normalize(raw);
            // [v1.12] 品牌：词表优先（印了品牌字样），无则 PN 前缀推断（只印零件号）
            if (brand == null) {
                brand = matchBrand(line, RAM_BRANDS);
                if (brand == null) brand = brandFromRamPn(line);
            }
            if (cap == null) {
                Matcher m = RE_RAM_CAP.matcher(line);
                if (m.find()) cap = m.group(1) + "GB";
            }
            if (typeFreq == null) {
                Matcher m = RE_RAM_TYPE.matcher(line);
                if (m.find()) typeFreq = ramTypeText(m);
            }
            // [v1.12] PN 完整串计数：同款内存 N 根时同一 PN 在标签上完整出现 N 次
            Matcher mp = RE_RAM_PN.matcher(line);
            while (mp.find()) {
                pnCount.merge(mp.group(), 1, Integer::sum);
            }
            Matcher ms = RE_SERIAL.matcher(line);
            while (ms.find()) {
                String tag = ms.group(1).replace("/", "").equals("PN") ? "PN" : "SN";
                String val = ms.group(2);
                if (!serials.containsValue(val)) serials.put(tag + ":" + val, val);
            }
        }
        // [v1.19] 海力士标签二次拾取（与三星布局不同的两个场景，看档案实拍照片总结）：
        //   a) "SN:" 标签独占一行（竖排标签换行截断）→ 下一行若是 SN 值（80AD/80CE 开头长串）则拾取
        //   b) 标签没印 SN: 字样时，独立成行的 80AD/80CE 长串就是序列号（三星 DDR5 同理 80CE 开头）
        // [v1.21] 截断/O 误识别修正（用户实拍海力士 SODIMM 反馈：18 位 SN 被 ML Kit 截成
        //   「SN:80ADO32549E40」+ 续行「D1268」，且数字 0 认成字母 O）：
        //   c) 80AD/80CE 开头的值，O 后接数字时替换为 0（这两家 DDR5 序列号不含字母 O）
        //   d) 行内 SN 值被截断时，下一行是纯字母数字短串（2-6 位）→ 拼接恢复完整 SN
        for (int i = 0; i < lines.size(); i++) {
            String line = normalize(lines.get(i)).trim();
            String next = i + 1 < lines.size() ? normalize(lines.get(i + 1)).trim() : "";
            // d) 行内 SN 值是 80AD/80CE 开头且下一行是 SN 尾段（字母数字混合短串）→ 拼接恢复完整 SN
            //    [v1.22] 门槛收紧：纯字母（GB/KOREA）与纯数字（512）不拼（isSnTail）
            Matcher mInline = RE_SERIAL.matcher(line);
            while (mInline.find()) {
                String tag = mInline.group(1).replace("/", "").equals("PN") ? "PN" : "SN";
                String rawVal = mInline.group(2);
                String val = fixRamSnDigitO(rawVal);
                if ("SN".equals(tag) && RE_RAM_SN_BARE_VAL.matcher(val).matches()
                        && isSnTail(next)) {
                    String joined = val + next;
                    if (!serials.containsValue(joined)) {
                        // 拼接成功 → 清掉截断短值（原始值与纠偏值两种 key 形态都删）
                        serials.remove("SN:" + rawVal);
                        serials.remove("SN:" + val);
                        serials.put("SN:" + joined, joined);
                    }
                }
            }
            // a) 标签独占行 → 跨行取值
            if (RE_RAM_SN_BARE.matcher(line).matches()
                    && RE_RAM_SN_BARE_VAL.matcher(next).matches()
                    && !serials.containsValue(next)) {
                serials.put("SN:" + next, next);
            }
            // b) 无标签独立长串行直接认 SN
            if (RE_RAM_SN_BARE_VAL.matcher(line).matches() && !serials.containsValue(line)) {
                serials.put("SN:" + line, line);
            }
        }
        // c) O→0 纠偏（循环后统一执行一次）：80AD/80CE 开头的 SN 值里 O 后接数字 → 替换为 0
        {
            java.util.LinkedHashMap<String, String> fixed = new java.util.LinkedHashMap<>();
            for (String key : serials.keySet()) {
                String val = serials.get(key);
                String fixedVal = fixRamSnDigitO(val);
                if (!fixedVal.equals(val)) {
                    fixed.put(key.substring(0, 3) + fixedVal, fixedVal);
                } else {
                    fixed.put(key, val);
                }
            }
            serials.clear();
            serials.putAll(fixed);
        }
        // [v1.07] 跨行补全：OCR 常把 "PC4-3200AA" 断成 "8GB 1Rx8 PC4" + "-3200AA…" 两行，
        // 行级匹配只拿到 "PC4"，把全文拼起来再找一次带频率的匹配
        if (typeFreq == null || !typeFreq.contains("MHz")) {
            StringBuilder all = new StringBuilder();
            for (String raw : lines) all.append(normalize(raw)).append(' ');
            Matcher m = RE_RAM_TYPE.matcher(all);
            while (m.find()) {
                if (m.group(2) != null) {
                    typeFreq = ramTypeText(m);
                    break;
                }
            }
        }
        // [v1.20] 频率兜底（档案实拍海力士 SODIMM 标签）："16GB 1Rx8 PC5" 与 "-5600B-SA0.00" 拆行后
        // 拼接顺序不定导致补全失败 → 全文搜主流 DDR 频率值，仅已有代数（typeFreq 非空）时附加
        if (typeFreq != null && !typeFreq.contains("MHz")) {
            StringBuilder all = new StringBuilder();
            for (String raw : lines) all.append(normalize(raw)).append(' ');
            Matcher m = RE_RAM_FREQ_BARE.matcher(all);
            if (m.find()) typeFreq = typeFreq + " " + m.group(1) + "MHz";
        }
        // [v1.12] 数量 = max(同 PN 最大重复次数, 不同 SN 数)，≥2 才标 xN
        for (int c : pnCount.values()) count = Math.max(count, c);
        int snDistinct = 0;
        for (String k : serials.keySet()) if (k.startsWith("SN:")) snDistinct++;
        count = Math.max(count, snDistinct);
        StringBuilder sb = new StringBuilder();
        if (brand != null) sb.append(brand);
        if (cap != null) {
            if (sb.length() > 0) sb.append(' ');
            sb.append(cap);
        }
        if (typeFreq != null) {
            if (sb.length() > 0) sb.append(' ');
            sb.append(typeFreq);
        }
        if (count > 1) sb.append(" x").append(count);
        for (String key : serials.keySet()) {
            sb.append(" | ").append(key);
        }
        return sb.length() == 0 ? null : sb.toString();
    }

    /** [v1.12] 代数+频率文本：PC4/PC5 统一表达为 DDR4/DDR5（用户习惯"代数"），LPDDR 原样 */
    private static String ramTypeText(Matcher m) {
        String gen = m.group(1);
        if ("PC4".equals(gen)) gen = "DDR4";
        else if ("PC5".equals(gen)) gen = "DDR5";
        return m.group(2) == null ? gen : gen + " " + m.group(2) + "MHz";
    }

    /** [v1.22] SN 截断续行判定：2-6 位、字母数字混合（含字母且含数字）的独立短串。
     *  ML Kit 把长 SN 截成两行时，第二段通常形如 "D1268"；
     *  纯字母（GB/KOREA/BA）、纯数字（512）与容量词（512GB/1TB）都排除，防止误拼进 SN。 */
    private static boolean isSnTail(String s) {
        if (s == null || !s.matches("[A-Z0-9]{2,6}")) return false;
        if (s.matches("\\d{1,4}(GB|TB)")) return false;   // 容量词（字母数字混合形态）
        boolean hasLetter = false, hasDigit = false;
        for (char c : s.toCharArray()) {
            if (Character.isDigit(c)) hasDigit = true;
            else hasLetter = true;
        }
        return hasLetter && hasDigit;
    }

    /** [v1.12] 内存 PN 前缀推断品牌（标签只印零件号不印品牌字样时） */
    private static String brandFromRamPn(String line) {
        for (String[] p : RAM_PN_PREFIXES) {
            if (line.contains(p[0])) return p[1];
        }
        return null;
    }

    /** [v1.21] 80AD/80CE 序列号纠偏：海力士/三星 DDR5 序列号不含字母 O，
     *  ML Kit 常把数字 0 认成 O（实拍 80ADO32549E40 应为 80AD032549E40）——
     *  仅这类前缀串生效：O 后接数字（或位于 E40 等尾部数字前）时替换为 0。 */
    private static String fixRamSnDigitO(String val) {
        if (val == null || !RE_RAM_SN_BARE_VAL.matcher(val.replace('O', '0')).matches()) return val;
        StringBuilder sb = new StringBuilder(val);
        for (int i = 4; i < sb.length(); i++) {          // 前缀 80AD/80CE（0-3 位）不动
            if (sb.charAt(i) == 'O') {
                boolean nextIsDigit = i + 1 < sb.length() && Character.isDigit(sb.charAt(i + 1));
                boolean prevIsDigit = i > 0 && Character.isDigit(sb.charAt(i - 1));
                if (nextIsDigit || prevIsDigit) sb.setCharAt(i, '0');
            }
        }
        return sb.toString();
    }

    /** [v1.07] 品牌词匹配（内存/固态共用）：返回命中的品牌词，无则 null。
     *  [v1.13] UNION MEMORY（联想品牌）按用户习惯输出简称 "UM" */
    private static String matchBrand(String line, String[] brands) {
        for (String b : brands) {
            if (line.contains(b)) return "UNION MEMORY".equals(b) ? "UM" : b;
        }
        return null;
    }

    /**
     * [v1.04] 固态硬盘标签结构化解析 → 摘要行，如：
     *   "SAMSUNG 1TB | SN:S5GXNX0R123456"
     * 侧重：品牌 + 容量(GB/TB) + 序列号。拼不出任何要素时返回 null。
     */
    public static String parseSsd(List<String> lines) {
        String brand = null, cap = null, kind = null;
        boolean isHdd = false;
        java.util.LinkedHashSet<String> serials = new java.util.LinkedHashSet<>();
        for (String raw : lines) {
            String line = normalize(raw);
            // [v1.20] 代工盘排除：海力士/三星为 HP/DELL 代工的固态，标签上「HP P/N: M16786-001」
            // 是代工零件号不是品牌（左下角大字 SK hynix 才是）——整行剔除代工段后再匹配品牌，
            // 否则「HP P/N」行会抢在品牌行前面命中 HP（档案实拍 BC711 NVMe 标签验证）
            String brandLine = line.replaceAll("(?:HP|DELL)\\s+P/?N\\s*[:：]?", " ");
            // [v1.13] 品牌：词表优先；无则 UM 固态 PN 推断（UM3017 等，标签只印 UM+数字）
            // [v1.19] 再补 MT 镁光 PN 前缀（MTFDKBA512QFM = MICRON）
            // [v1.20] 再补 HFM 海力士型号前缀（HFM512GD3JX013N = SK HYNIX BC711 代工盘型号串）
            if (brand == null) {
                brand = matchBrand(brandLine, SSD_BRANDS);
                if (brand == null && RE_UM_SSD_PN.matcher(line).find()) brand = "UM";
                if (brand == null && line.contains("MTFDK")) brand = "MICRON";
                if (brand == null && line.matches(".*\\bHFM\\d{2,}[A-Z0-9]*.*")) brand = "SK HYNIX";
            }
            if (cap == null) {
                Matcher m = RE_SSD_CAP.matcher(line);
                if (m.find()) cap = m.group(1).replace(" ", "");
            }
            // [v1.07] 接口/形态参数：NVMe > M.2 > SATA（按标签原样附加）
            if (kind == null) {
                if (line.contains("NVME")) kind = "NVMe";
                else if (line.contains("M.2")) kind = "M.2";
                else if (line.contains("SATA")) kind = "SATA";
            }
            // [v1.19] 机械盘标记：东芝/希捷 HDD 标签（"硬盘 HDD" / "7200RPM"）
            // ——档案实拍：TOSHIBA 1.0TB SATA HDD，协议仍是 SATA，形态标 HDD 与固态区分
            if (!isHdd && (line.contains("HDD") || line.matches(".*\\d{4}\\s?RPM.*"))) isHdd = true;
            // [v1.19] 裸容量：群联等标签只印 "P0327 NVME 512" 无 GB 后缀时会漏；
            // 行里已有 NVME/SSD 关键词时，256/480/512/960 等裸数字按 GB 认（档案实测群联标签场景）
            if (cap == null && (line.contains("NVME") || line.contains("SSD"))) {
                Matcher m = RE_SSD_BARE_CAP.matcher(line);
                if (m.find()) cap = m.group(1) + "GB";
            }
            Matcher ms = RE_SERIAL.matcher(line);
            while (ms.find()) {
                String tag = ms.group(1).replace("/", "").equals("PN") ? "PN" : "SN";
                serials.add(tag + ":" + ms.group(2));
            }
        }
        // [v1.22] 固态 SN 截断拼接（与内存同款问题）：ML Kit 把长 SN 截成两行时，
        // 行内 SN 值（≥10 位）+ 下一行是字母数字混合短串（D1268 形态）→ 拼接恢复完整 SN；
        // 纯字母（GB/KOREA）与纯数字（512）不拼，防误伤。serials 是 set，替换需先删截断短值。
        {
            java.util.LinkedHashSet<String> merged = new java.util.LinkedHashSet<>();
            java.util.LinkedHashSet<String> consumed = new java.util.LinkedHashSet<>();
            for (int i = 0; i < lines.size(); i++) {
                String line = normalize(lines.get(i)).trim();
                String next = i + 1 < lines.size() ? normalize(lines.get(i + 1)).trim() : "";
                String rawSn = null;
                Matcher mSn = RE_SERIAL.matcher(line);
                while (mSn.find()) {
                    if ("SN".equals(mSn.group(1).replace("/", "")) && mSn.group(2).length() >= 10) {
                        rawSn = mSn.group(2);
                    }
                }
                if (rawSn != null && isSnTail(next)) {
                    String joined = rawSn + next;
                    if (!serials.contains("SN:" + joined)) {
                        consumed.add("SN:" + rawSn);
                        merged.add("SN:" + joined);
                    }
                }
            }
            serials.removeAll(consumed);
            serials.addAll(merged);
        }
        // [v1.19] 机械盘形态：识别到 HDD/RPM 时输出 "SATA HDD"（无接口时也补上 SATA 默认值）
        if (isHdd) kind = "SATA HDD";
        // [v1.12] 数量：不同 SN ≥2 块时标 xN（如两块同款固态）
        int snCount = 0;
        for (String s : serials) if (s.startsWith("SN:")) snCount++;
        StringBuilder sb = new StringBuilder();
        if (brand != null) sb.append(brand);
        if (cap != null) {
            if (sb.length() > 0) sb.append(' ');
            sb.append(cap);
        }
        if (kind != null) {
            if (sb.length() > 0) sb.append(' ');
            sb.append(kind);
        }
        if (snCount > 1) sb.append(" x").append(snCount);
        for (String s : serials) {
            sb.append(" | ").append(s);
        }
        return sb.length() == 0 ? null : sb.toString();
    }

    /** 解析主机标签照片 OCR 文本行 */
    public static HostResult parseHost(List<String> lines) {
        StringBuilder all = new StringBuilder();
        for (String raw : lines) {
            all.append(normalize(raw)).append('\n');
        }
        String text = all.toString();
        HostResult r = new HostResult();
        Matcher m = RE_HOST_SN.matcher(text);
        java.util.LinkedHashSet<String> seen = new java.util.LinkedHashSet<>();
        while (m.find()) {
            String v = m.group(1).replaceAll("-+$", "");
            if (!seen.contains(v)) {
                seen.add(v);
                r.snCandidates.add(v);
                if (r.snCandidates.size() >= 5) break;
            }
        }
        if (!r.snCandidates.isEmpty()) r.sn = r.snCandidates.get(0);
        // [v1.19] 联想主机条码行兜底：标签没有「S/N」字样，SN 印在底部条码——
        // 「(1S)13ASCT01WW GM1GB370」行末段（7-8 位字母数字）即出厂编号
        // （13ASCT01WW 是机器类型码，档案实拍 ThinkCentre M90a 标签验证）
        if (r.snCandidates.isEmpty()) {
            Matcher lm = RE_LENOVO_SN_BAR.matcher(text);
            while (lm.find()) {
                String v = lm.group(1);
                if (!seen.contains(v)) {
                    seen.add(v);
                    r.snCandidates.add(v);
                }
            }
            if (!r.snCandidates.isEmpty()) r.sn = r.snCandidates.get(0);
        }
        m = RE_HOST_BATCH.matcher(text);
        if (m.find()) r.batch = m.group(1);
        // [v1.03] 型号在原始行上匹配：保留原样大小写（ThinkCentre M770e MEL2），逐行收集候选
        for (int i = 0; i < lines.size(); i++) {
            if (r.machineModelCandidates.size() >= 5) break;
            String line = lines.get(i) == null ? "" : lines.get(i).trim();
            if (line.isEmpty()) continue;
            Matcher mm = RE_MACHINE_MODEL.matcher(line);
            if (mm.find()) {
                String v = cleanModelValue(mm.group(1));
                // [v1.12] 标签值断行补全：ML Kit 常把「产品型号：Vostro」和「3020 SFF」拆成两行，
                // 值不含数字（纯品牌词）且下一行是「数字开头的型号段」时拼成完整型号
                if (!v.isEmpty() && !v.matches(".*\\d.*") && i + 1 < lines.size()) {
                    String next = lines.get(i + 1) == null ? "" : lines.get(i + 1).trim();
                    if (next.matches("\\d{2,5}[A-Za-z0-9\\s-]{0,10}")) {
                        String v2 = cleanModelValue(next);
                        if (!v2.isEmpty()) v = v + " " + v2;
                    }
                }
                if (!v.isEmpty() && !r.machineModelCandidates.contains(v)) {
                    r.machineModelCandidates.add(v);
                }
            }
        }
        // [v1.07] 兜底：标签上没有「型号/MODEL」字样时，主机品牌系列大字行（ThinkCentre M770e 等）也算候选
        if (r.machineModelCandidates.size() < 5) {
            for (String raw : lines) {
                if (r.machineModelCandidates.size() >= 5) break;
                String line = raw == null ? "" : raw.trim();
                if (line.isEmpty()) continue;
                if (RE_MACHINE_MODEL.matcher(line).find()) continue;   // 已按标签识别过的行跳过
                if (RE_MACHINE_BRAND_LINE.matcher(line).find()) {
                    String v = cleanModelValue(line);
                    if (!v.isEmpty() && !r.machineModelCandidates.contains(v)) {
                        r.machineModelCandidates.add(v);
                    }
                }
                // [v1.13] 联想 Tiny 小主机（无品牌字样）："P3 Tiny Gen 2 (1SWMT - M30KG - S4HP00" → "P3 Tiny Gen 2"
                else {
                    Matcher tm = RE_TINY_MODEL.matcher(line);
                    if (tm.find()) {
                        String v = tm.group(2) == null
                                ? tm.group(1) + " Tiny"
                                : tm.group(1) + " Tiny Gen " + tm.group(2);
                        if (!r.machineModelCandidates.contains(v)) {
                            r.machineModelCandidates.add(v);
                        }
                    }
                }
            }
        }
        // [v1.09] 兜底2：标签只印品牌没印具体型号（如「中小企业商用台式机Vostro」）→ 填品牌词让用户补全
        if (r.machineModelCandidates.isEmpty()) {
            for (String raw : lines) {
                String line = raw == null ? "" : normalize(raw);
                if (line.isEmpty()) continue;
                for (String b : MACHINE_BRANDS) {
                    if (line.contains(b.toUpperCase(Locale.US))) {
                        r.machineModelCandidates.add(b);
                        break;
                    }
                }
                if (!r.machineModelCandidates.isEmpty()) break;
            }
        }
        if (!r.machineModelCandidates.isEmpty()) r.machineModel = r.machineModelCandidates.get(0);
        return r;
    }

    /** [v1.03] 清理型号值：去掉首尾杂质、截掉粘连的下一字段 / 网址 */
    private static String cleanModelValue(String s) {
        // [v1.07] 全角/不间断空格归一为半角（String.trim 去不掉 U+3000/U+00A0，会残留在值首尾）
        String v = s == null ? "" : s.replace('\u3000', ' ').replace('\u00A0', ' ').trim();
        Matcher cut = RE_MODEL_TAIL_CUT.matcher(v);
        if (cut.find()) v = v.substring(0, cut.start()).trim();
        // 去掉行尾残留的标点
        while (v.endsWith(":") || v.endsWith("：") || v.endsWith("-") || v.endsWith(",")) {
            v = v.substring(0, v.length() - 1).trim();
        }
        return v;
    }

    /** 提取规范化的 CPU 型号，如 I7-14700 / ULTRA 7 265 / RYZEN 7 5800X */
    private static String matchModel(String line) {
        // Intel Core i3-i9（最主流，优先）
        Matcher m = RE_MODEL.matcher(line);
        if (m.find()) {
            String suffix = m.group(3) == null ? "" : m.group(3);
            if ("TM".equals(suffix)) suffix = "";   // "CORE(TM)" 的 TM 不是型号后缀
            return "I" + m.group(1) + "-" + m.group(2) + suffix;
        }
        // [v1.10] Intel Core Ultra（同行）：CORE ULTRA 7 265
        Matcher u = RE_ULTRA.matcher(line);
        if (u.find()) return "ULTRA " + u.group(1) + " " + u.group(2);
        // [v1.10] AMD Ryzen（同行）：AMD RYZEN 7 5800X
        Matcher a = RE_AMD.matcher(line);
        if (a.find()) return "RYZEN " + a.group(1) + " " + a.group(2);
        return null;
    }

    /**
     * ATPO 候选排序（CPU 编号，纯数字 5 位）：
     *   3 分：整行就是 5 位数字（基板边缘编号通常是独立一行）；或 [v1.13] 分段数字流拼出的 0 开头编号
     *   2 分：以 0 开头的 5 位数字；其他数字流拼接结果
     *   1 分：其他
     * [v1.13] U 系列编号印在基板右上角竖排（如 05378），OCR 常拆成 "0537"+"8" 两行或
     *   "0","5","3","7","8" 单字符行 → 连续纯数字短行依序拼成 5 位候选（遇字母行清流防串位）。
     * 扫描前先把 CPU 型号（如 I7-14700 里的 14700）抹掉，避免误判为编号。
     */
    private static List<String> rankAtpo(List<String> lines) {
        Map<String, Integer> best = new LinkedHashMap<>();
        StringBuilder digitStream = new StringBuilder();   // [v1.13] 连续数字短行流（竖排编号）
        for (String raw : lines) {
            String line = stripModel(normalize(raw)).trim();
            // [v1.13] 纯数字短行（1-4 位）：追加进流，凑满 5 位即候选（U 系列右上角竖排编号）
            if (line.matches("\\d{1,4}")) {
                if (digitStream.length() == 5) digitStream.setLength(0);   // 上一个候选已满，重开
                digitStream.append(line);
                if (digitStream.length() == 5) {
                    String comb = digitStream.toString();
                    best.put(comb, comb.startsWith("0") ? 3 : 2);
                }
                continue;
            }
            digitStream.setLength(0);   // 非纯数字行切断流（防不同区域数字串位）
            Matcher m = RE_ATPO.matcher(line);
            while (m.find()) {
                String token = m.group(1);
                int score = 1;
                if (line.matches("\\d{5}")) {
                    score = 3;
                } else if (token.startsWith("0")) {
                    score = 2;
                }
                Integer old = best.get(token);
                if (old == null || score > old) best.put(token, score);
            }
        }
        List<String> tokens = new ArrayList<>(best.keySet());
        tokens.sort((a, b) -> best.get(b) - best.get(a));
        // 最多给 5 个候选
        return tokens.subList(0, Math.min(5, tokens.size()));
    }

    /** 把行内命中的 CPU 型号片段替换成等长空格（防 14700 被当成 ATPO） */
    private static String stripModel(String line) {
        Matcher m = RE_MODEL.matcher(line);
        StringBuffer sb = new StringBuffer();
        while (m.find()) {
            String suffix = m.group(3) == null ? "" : m.group(3);
            if ("TM".equals(suffix)) suffix = "";
            int len = 2 + m.group(2).length() + suffix.length();
            char[] spaces = new char[len];
            Arrays.fill(spaces, ' ');
            m.appendReplacement(sb, Matcher.quoteReplacement(new String(spaces)));
        }
        m.appendTail(sb);
        return sb.toString();
    }
}
