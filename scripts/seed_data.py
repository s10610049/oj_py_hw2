"""24 original teaching problems with self-authored data, never third-party tests.

Expected answers are explicit constants or elementary closed-form fixture patterns.
SEED_SOLUTIONS are separate executable references for verification, not API payloads.
"""

from textwrap import dedent


def cases(*rows):
    """Make input/output fixtures without calculating problem answers."""
    return [{"input": source, "output": answer} for source, answer in rows]


def line(values):
    return " ".join(map(str, values)) + "\n"


def array_input(values):
    return f"{len(values)}\n" + line(values)


def pairs_input(pairs):
    return f"{len(pairs)}\n" + "".join(line(pair) for pair in pairs)


def make_problem(key, title, description, inputs, outputs, constraints, cases, tags, difficulty):
    return {
        "id": key,
        "title": title,
        "description": description,
        "input_description": inputs,
        "output_description": outputs,
        "constraints": constraints,
        "samples": cases[:2],
        "testcases": cases,
        "tags": tags,
        "difficulty": difficulty,
        "source": "项目原创演示题 · 自建测试数据",
        "author": "OJ 项目",
        "hint": "先从样例出发，再检查边界条件。",
        "time_limit": 2.0,
        "memory_limit": 128,
    }


DEMO_PROBLEMS = [
    make_problem(
        "DEMO-001",
        "两笔账目",
        "记账本新增了两笔整数金额，收入为正、支出为负。请计算这两笔金额的合计。",
        "一行两个整数 a 和 b，以空格分隔。",
        "输出一个整数，表示 a + b。",
        "−10⁹ ≤ a, b ≤ 10⁹。",
        [
            {"input": f"{a} {b}\n", "output": f"{a+b}\n"}
            for a, b in [
                (12, 8),
                (-7, 3),
                (0, 0),
                (10**9, 10**9),
                (-(10**9), -(10**9)),
                (7, -7),
                (1, -2),
                (-123456789, 987654321),
            ]
        ],
        ["输入输出", "整数运算"],
        "入门",
    ),
    make_problem(
        "DEMO-002",
        "连续晴天",
        "气象记录用 1 表示晴天、0 表示非晴天。给定连续 n 天记录，求最长连续晴天的天数。",
        "第一行一个整数 n；第二行 n 个整数，每个为 0 或 1。",
        "输出最长连续 1 的数量；没有晴天时输出 0。",
        "1 ≤ n ≤ 100000。",
        [
            {"input": f"{len(row)}\n{' '.join(map(str, row))}\n", "output": f"{answer}\n"}
            for row, answer in [
                ([1, 1, 0, 1], 2),
                ([0, 0, 0], 0),
                ([1], 1),
                ([0], 0),
                ([1] * 1000, 1000),
                ([0, 1] * 500, 1),
                ([1, 0, 1, 1, 1, 0, 1], 3),
                ([1] * 100000, 100000),
            ]
        ],
        ["遍历", "状态维护"],
        "普及-",
    ),
    make_problem(
        "DEMO-003",
        "读书计划",
        "每本书有整数页数。你要回答若干个查询：从第 l 本到第 r 本（含端点）的总页数是多少？",
        "第一行 n q。第二行 n 个非负整数页数。接下来 q 行，每行两个整数 l r，编号从 1 开始。",
        "每个查询输出一行整数。",
        "1 ≤ n,q ≤ 100000；0 ≤ 页数 ≤ 10⁹；1 ≤ l ≤ r ≤ n。",
        [
            {"input": "4 3\n10 20 30 40\n1 4\n2 3\n4 4\n", "output": "100\n50\n40\n"},
            {"input": "1 2\n0\n1 1\n1 1\n", "output": "0\n0\n"},
            {
                "input": "3 2\n1000000000 1000000000 1000000000\n1 3\n2 3\n",
                "output": "3000000000\n2000000000\n",
            },
            {"input": "5 4\n0 5 0 8 0\n1 1\n2 4\n3 5\n5 5\n", "output": "0\n13\n8\n0\n"},
            {"input": "6 3\n1 2 3 4 5 6\n1 6\n2 5\n3 4\n", "output": "21\n14\n7\n"},
            {"input": "2 3\n9 1\n1 1\n2 2\n1 2\n", "output": "9\n1\n10\n"},
            {
                "input": "10000 3\n" + line([1] * 10000) + "1 10000\n2 9999\n5000 5000\n",
                "output": "10000\n9998\n1\n",
            },
            {
                "input": "1000 2\n" + line([10**9] * 1000) + "1 1000\n999 1000\n",
                "output": "1000000000000\n2000000000\n",
            },
        ],
        ["前缀和", "查询"],
        "普及-",
    ),
    make_problem(
        "DEMO-004",
        "任务依赖",
        "一个任务执行前可能需要另一个任务先完成。给定这些依赖，判断是否存在循环依赖。图中的边 u → v 表示 u 必须在 v 前完成；不需要启动真实线程。",
        "第一行 n m；随后 m 行，每行 u v 表示一条有向依赖边。",
        "存在有向环输出 YES，否则输出 NO。",
        "1 ≤ n ≤ 100000；0 ≤ m ≤ 200000；1 ≤ u,v ≤ n，允许自环和重复边。",
        [
            {"input": "3 3\n1 2\n2 3\n3 1\n", "output": "YES\n"},
            {"input": "3 2\n1 2\n1 3\n", "output": "NO\n"},
            {"input": "1 0\n", "output": "NO\n"},
            {"input": "1 1\n1 1\n", "output": "YES\n"},
            {"input": "4 3\n1 2\n3 4\n4 3\n", "output": "YES\n"},
            {"input": "2 2\n1 2\n1 2\n", "output": "NO\n"},
            {
                "input": "10000 9999\n" + "".join(f"{i} {i+1}\n" for i in range(1, 10000)),
                "output": "NO\n",
            },
            {
                "input": "10000 10000\n"
                + "".join(f"{i} {i+1}\n" for i in range(1, 10000))
                + "10000 1\n",
                "output": "YES\n",
            },
        ],
        ["有向图", "拓扑排序"],
        "普及+/提高-",
    ),
    make_problem(
        "DEMO-005",
        "仓库装箱",
        "仓库有 n 件物品，每只箱子最多装 k 件。物品不可拆分，最后一只箱子可以不装满。求至少需要多少只箱子；没有物品时不需要箱子。",
        "一行两个整数 n k。",
        "输出最少箱子数。",
        "0 ≤ n ≤ 10¹⁸；1 ≤ k ≤ 10⁹。",
        cases(
            ("13 5\n", "3\n"),
            ("0 7\n", "0\n"),
            ("1 1\n", "1\n"),
            ("9 3\n", "3\n"),
            ("10 3\n", "4\n"),
            ("1 1000000000\n", "1\n"),
            ("1000000000000000000 1000000000\n", "1000000000\n"),
            ("1000000000000000000 3\n", "333333333333333334\n"),
        ),
        ["整数运算", "向上取整"],
        "入门",
    ),
    make_problem(
        "DEMO-006",
        "训练等级",
        "一次训练的得分为整数 s。90 分及以上为 A，75 至 89 分为 B，60 至 74 分为 C，低于 60 分为 D。请给出得分对应的等级。",
        "一行一个整数 s。",
        "输出一个大写字母 A、B、C 或 D。",
        "0 ≤ s ≤ 100。",
        cases(
            ("90\n", "A\n"),
            ("74\n", "C\n"),
            ("0\n", "D\n"),
            ("59\n", "D\n"),
            ("60\n", "C\n"),
            ("75\n", "B\n"),
            ("89\n", "B\n"),
            ("100\n", "A\n"),
        ),
        ["条件判断", "边界"],
        "入门",
    ),
    make_problem(
        "DEMO-007",
        "编号校验和",
        "将一个非负整数编号的十进制各位数字相加，得到校验和。例如 5030 的校验和为 5+0+3+0=8。请计算给定编号的校验和。",
        "一行一个非负整数 n，不含多余前导零。",
        "输出各位数字之和。",
        "0 ≤ n ≤ 10¹⁸。",
        cases(
            ("5030\n", "8\n"),
            ("999\n", "27\n"),
            ("0\n", "0\n"),
            ("1\n", "1\n"),
            ("1000000000000000000\n", "1\n"),
            ("999999999999999999\n", "162\n"),
            ("100000000000000001\n", "2\n"),
            ("123456789012345678\n", "81\n"),
        ),
        ["循环", "整数运算"],
        "入门",
    ),
    make_problem(
        "DEMO-008",
        "阶乘的尾巴",
        "定义 n! 为从 1 到 n 的所有整数之积，且 0!=1。请计算 n! 的十进制表示末尾连续有多少个 0，不要求输出阶乘本身。",
        "一行一个整数 n。",
        "输出末尾连续 0 的个数。",
        "0 ≤ n ≤ 10⁹。",
        cases(
            ("10\n", "2\n"),
            ("25\n", "6\n"),
            ("0\n", "0\n"),
            ("1\n", "0\n"),
            ("5\n", "1\n"),
            ("24\n", "4\n"),
            ("125\n", "31\n"),
            ("1000000000\n", "249999998\n"),
        ),
        ["循环", "因数统计"],
        "普及-",
    ),
    make_problem(
        "DEMO-009",
        "镜面口令",
        "一段口令只含小写英文字母。若从左向右读与从右向左读完全相同，就称它为镜面口令。请判断给定口令是否满足条件。",
        "一行非空字符串 s。",
        "是镜面口令输出 YES，否则输出 NO。",
        "1 ≤ |s| ≤ 100000；字符仅为 a 至 z。",
        cases(
            ("level\n", "YES\n"),
            ("python\n", "NO\n"),
            ("a\n", "YES\n"),
            ("aa\n", "YES\n"),
            ("ab\n", "NO\n"),
            ("abca\n", "NO\n"),
            ("a" * 99999 + "b\n", "NO\n"),
            ("ab" * 25000 + "ba" * 25000 + "\n", "YES\n"),
        ),
        ["字符串", "双指针"],
        "入门",
    ),
    make_problem(
        "DEMO-010",
        "字母值日生",
        "统计一段小写字母串中每个字母的出现次数。出现次数最多的字母成为值日生；若并列，选择字母表顺序最靠前的字母。",
        "一行非空小写字母串 s。",
        "输出所选字母和它的出现次数，以一个空格分隔。",
        "1 ≤ |s| ≤ 100000；字符仅为 a 至 z。",
        cases(
            ("banana\n", "a 3\n"),
            ("ccbb\n", "b 2\n"),
            ("z\n", "z 1\n"),
            ("abcdefghijklmnopqrstuvwxyz\n", "a 1\n"),
            ("aaaa\n", "a 4\n"),
            ("abacabad\n", "a 4\n"),
            ("abc" * 30000 + "\n", "a 30000\n"),
            ("z" * 50000 + "a" * 49999 + "\n", "z 50000\n"),
        ),
        ["字符串", "计数", "数组"],
        "普及-",
    ),
    make_problem(
        "DEMO-011",
        "路标压缩",
        "一串小写字母表示沿途路标。将每个极长连续相同字母段替换为字母紧接该段长度，例如 aaabb 变为 a3 b2。即使长度为 1 也必须写出数字 1。",
        "一行非空小写字母串 s。",
        "从左到右输出各段的字母和长度，相邻段以一个空格分隔。",
        "1 ≤ |s| ≤ 100000；字符仅为 a 至 z。",
        cases(
            ("aaaabbcca\n", "a4 b2 c2 a1\n"),
            ("abc\n", "a1 b1 c1\n"),
            ("z\n", "z1\n"),
            ("zz\n", "z2\n"),
            ("abba\n", "a1 b2 a1\n"),
            ("aaabaaa\n", "a3 b1 a3\n"),
            ("x" * 100000 + "\n", "x100000\n"),
            ("ab" * 1000 + "\n", " ".join(["a1", "b1"] * 1000) + "\n"),
        ),
        ["字符串", "分段扫描"],
        "普及-",
    ),
    make_problem(
        "DEMO-012",
        "第二种高度",
        "给定 n 个观测高度，重复高度只算一种。求严格小于最大高度的最大高度，即第二大的不同数值。若不足两种不同高度，输出 NONE。",
        "第一行整数 n；第二行 n 个整数高度。",
        "输出第二大的不同高度，或大写单词 NONE。",
        "1 ≤ n ≤ 100000；−10⁹ ≤ 高度 ≤ 10⁹。",
        cases(
            (array_input([3, 1, 4, 4, 2]), "3\n"),
            (array_input([7, 7]), "NONE\n"),
            (array_input([1]), "NONE\n"),
            (array_input([-5, -2, -9]), "-5\n"),
            (array_input([1, 2]), "1\n"),
            (array_input([2, 1]), "1\n"),
            (array_input([-(10**9), 10**9, 0]), "0\n"),
            (array_input(range(10000)), "9998\n"),
        ),
        ["数组", "去重", "排序"],
        "普及-",
    ),
    make_problem(
        "DEMO-013",
        "环形展示牌",
        "展示牌上依次放着 n 个整数。每次右移会把最后一个数移到最前面，其余数向右移动一格。求连续右移 k 次后的排列。",
        "第一行 n k；第二行 n 个整数。",
        "按顺序输出移动后的 n 个整数，以空格分隔。",
        "1 ≤ n ≤ 100000；0 ≤ k ≤ 10¹⁸；各数绝对值不超过 10⁹。",
        cases(
            ("5 2\n1 2 3 4 5\n", "4 5 1 2 3\n"),
            ("1 100\n9\n", "9\n"),
            ("3 0\n1 2 3\n", "1 2 3\n"),
            ("5 5\n1 2 3 4 5\n", "1 2 3 4 5\n"),
            ("5 7\n1 2 3 4 5\n", "4 5 1 2 3\n"),
            ("3 1\n-1 -2 -3\n", "-3 -1 -2\n"),
            ("4 1000000000000000000\n1 2 3 4\n", "1 2 3 4\n"),
            ("10000 9999\n" + line(range(1, 10001)), line([*range(2, 10001), 1])),
        ),
        ["数组", "取模", "模拟"],
        "普及-",
    ),
    make_problem(
        "DEMO-014",
        "晨跑榜单",
        "n 位同学按输入顺序编号为 1 至 n，每人有一个训练积分。榜单按积分从高到低排列，积分相同时编号较小者在前。请输出榜单上的编号顺序。",
        "第一行整数 n；第二行 n 个非负整数积分。",
        "输出排序后的 n 个编号，以空格分隔。",
        "1 ≤ n ≤ 100000；0 ≤ 积分 ≤ 10⁹。",
        cases(
            (array_input([90, 100, 90, 70]), "2 1 3 4\n"),
            (array_input([7, 7, 7]), "1 2 3\n"),
            (array_input([0]), "1\n"),
            (array_input([3, 2, 1]), "1 2 3\n"),
            (array_input([1, 2, 3]), "3 2 1\n"),
            (array_input([0, 10**9, 0, 10**9]), "2 4 1 3\n"),
            (array_input([42] * 10000), line(range(1, 10001))),
            (array_input(range(10000)), line(range(10000, 0, -1))),
        ),
        ["排序", "多关键字"],
        "普及-",
    ),
    make_problem(
        "DEMO-015",
        "巡查区段",
        "数轴上有 n 个需要巡查的闭区间。相交的区间合并为一个区段，共用端点也算相交。反复合并后，求剩下多少个互不相交的区段；仅整数相邻但没有共同点的区间不合并。",
        "第一行整数 n；随后 n 行，每行两个整数 l r，表示闭区间 [l,r]。",
        "输出合并后的区段数。",
        "1 ≤ n ≤ 100000；−10⁹ ≤ l ≤ r ≤ 10⁹。",
        cases(
            (pairs_input([(1, 3), (2, 4), (6, 7)]), "2\n"),
            (pairs_input([(1, 2), (2, 3)]), "1\n"),
            (pairs_input([(0, 0)]), "1\n"),
            (pairs_input([(0, 10), (2, 3), (4, 8)]), "1\n"),
            (pairs_input([(5, 6), (1, 2), (3, 4)]), "3\n"),
            (pairs_input([(-5, -2), (-1, 1)]), "2\n"),
            (pairs_input([(1, 1)] * 5), "1\n"),
            (pairs_input([(2 * i, 2 * i + 1) for i in range(10000)]), "10000\n"),
        ),
        ["排序", "区间合并"],
        "普及-",
    ),
    make_problem(
        "DEMO-016",
        "书架定位",
        "书架编号按非递减顺序排列，允许重复。每次给出目标编号 x，找出第一个编号不小于 x 的位置。位置从 1 开始；若不存在，返回 n+1。",
        "第一行 n q；第二行 n 个有序整数；接下来 q 行，每行一个整数 x。",
        "每个查询输出一行位置。",
        "1 ≤ n,q ≤ 100000；所有编号及 x 的绝对值不超过 10⁹。",
        cases(
            ("5 4\n1 2 2 5 9\n2\n0\n10\n5\n", "2\n1\n6\n4\n"),
            ("1 2\n3\n3\n4\n", "1\n2\n"),
            ("3 3\n7 7 7\n6\n7\n8\n", "1\n1\n4\n"),
            ("3 3\n-5 -2 0\n-3\n-5\n1\n", "2\n1\n4\n"),
            ("2 2\n-1000000000 1000000000\n-1000000000\n1000000000\n", "1\n2\n"),
            ("4 2\n1 3 5 7\n4\n7\n", "3\n4\n"),
            ("1 1\n0\n-1\n", "1\n"),
            (
                "100000 4\n" + line(range(100000)) + "0\n99999\n100000\n50000\n",
                "1\n100000\n100001\n50001\n",
            ),
        ),
        ["二分查找", "查询"],
        "普及-",
    ),
    make_problem(
        "DEMO-017",
        "分堆搬运",
        "仓库有 n 堆货物，第 i 堆有 aᵢ 件。选择正整数搬运速度 k 后，"
        "每堆单独占用 ceil(aᵢ/k) 个整小时，即把 aᵢ/k 向上取整，"
        "不能把不同堆的余量合并到同一小时。求能在 h 小时内搬完全部货物的最小速度。",
        "第一行 n h；第二行 n 个正整数 aᵢ。",
        "输出最小正整数速度 k。",
        "1 ≤ n ≤ 10000；n ≤ h ≤ 10¹⁸；1 ≤ aᵢ ≤ 10⁹。",
        cases(
            ("3 9\n5 8 14\n", "4\n"),
            ("4 4\n18 7 25 3\n", "25\n"),
            ("1 1\n1\n", "1\n"),
            ("1 100\n100\n", "1\n"),
            ("2 3\n3 3\n", "3\n"),
            ("3 6\n6 6 6\n", "3\n"),
            ("4 1000000000\n" + line([10**9] * 4), "4\n"),
            ("10000 10000\n" + line([10**9] * 10000), "1000000000\n"),
        ),
        ["二分答案", "向上取整"],
        "普及+/提高-",
    ),
    make_problem(
        "DEMO-018",
        "括号检查站",
        "一个记录串只由圆括号、方括号和花括号组成。每个左括号必须按后进先出的顺序与同类型右括号配对，且不能剩余任何括号。判断整个记录串是否合法。",
        "一行非空括号串 s。",
        "完全配对输出 YES，否则输出 NO。",
        "1 ≤ |s| ≤ 100000；字符仅为 ()[]{}。",
        cases(
            ("([]){}\n", "YES\n"),
            ("([)]\n", "NO\n"),
            ("()\n", "YES\n"),
            ("(\n", "NO\n"),
            (")(\n", "NO\n"),
            ("{[()]}\n", "YES\n"),
            ("((())\n", "NO\n"),
            ("(" * 50000 + ")" * 50000 + "\n", "YES\n"),
        ),
        ["栈", "字符串"],
        "普及-",
    ),
    make_problem(
        "DEMO-019",
        "服务窗口",
        "窗口使用先进先出的队列，初始为空。PUSH x 把整数 x 放入队尾；"
        "POP 移出并输出队首；FRONT 只查看并输出队首。"
        "空队列执行 POP 或 FRONT 时输出 EMPTY，队列保持为空。",
        "第一行操作数 q；接下来 q 行，每行是 PUSH x、POP 或 FRONT。",
        "每次 POP 或 FRONT 输出一行结果；PUSH 不输出。若没有查询或移出操作，则不输出任何内容。",
        "1 ≤ q ≤ 100000；−10⁹ ≤ x ≤ 10⁹。",
        cases(
            ("8\nPUSH 4\nFRONT\nPUSH 9\nPOP\nPOP\nPOP\nPUSH -1\nFRONT\n", "4\n4\n9\nEMPTY\n-1\n"),
            ("2\nFRONT\nPOP\n", "EMPTY\nEMPTY\n"),
            ("1\nPUSH 0\n", ""),
            ("3\nPUSH 0\nPOP\nFRONT\n", "0\nEMPTY\n"),
            ("4\nPUSH 1\nPUSH 2\nFRONT\nFRONT\n", "1\n1\n"),
            ("5\nPUSH 1\nPOP\nPUSH 2\nPOP\nPOP\n", "1\n2\nEMPTY\n"),
            ("4\nPUSH -1000000000\nPUSH 1000000000\nPOP\nPOP\n", "-1000000000\n1000000000\n"),
            (
                "20000\n" + "".join(f"PUSH {i}\n" for i in range(10000)) + "POP\n" * 10000,
                "".join(f"{i}\n" for i in range(10000)),
            ),
        ),
        ["队列", "模拟"],
        "普及-",
    ),
    make_problem(
        "DEMO-020",
        "共享会议室",
        "一间会议室收到 n 个预约，预约占用半开区间 [s,e)。你可以选择部分预约，但任意两个被选预约不能重叠。结束时刻等于下一场开始时刻时允许衔接。求最多能接受多少个预约。",
        "第一行整数 n；接下来 n 行，每行两个整数 s e。",
        "输出最多能接受的预约数。",
        "1 ≤ n ≤ 100000；0 ≤ s < e ≤ 10⁹。",
        cases(
            (pairs_input([(1, 3), (2, 4), (3, 5), (5, 6)]), "3\n"),
            (pairs_input([(0, 10), (1, 2), (2, 3)]), "2\n"),
            (pairs_input([(0, 1)]), "1\n"),
            (pairs_input([(1, 3), (1, 2), (1, 4)]), "1\n"),
            (pairs_input([(7, 8), (1, 2), (4, 5)]), "3\n"),
            (pairs_input([(0, 1), (1, 2), (2, 3)]), "3\n"),
            (pairs_input([(0, 100), (1, 10), (10, 20), (20, 30)]), "3\n"),
            (pairs_input([(i, i + 1) for i in range(10000)]), "10000\n"),
        ),
        ["贪心", "排序", "区间调度"],
        "普及+/提高-",
    ),
    make_problem(
        "DEMO-021",
        "隔日采集",
        "连续 n 天各有一个整数收益，可以选择任意一些天进行采集，但不能同时选择相邻两天。允许一天都不选，此时收益为 0。求可获得的最大收益总和。",
        "第一行整数 n；第二行 n 个整数收益，按日期顺序给出。",
        "输出最大收益总和。",
        "1 ≤ n ≤ 100000；每个收益介于 −10⁹ 与 10⁹ 之间。",
        cases(
            (array_input([6, 2, 10, 3, 7]), "23\n"),
            (array_input([-5, -1, -9]), "0\n"),
            (array_input([8]), "8\n"),
            (array_input([0]), "0\n"),
            (array_input([4, 1, 1, 9, 2, 8]), "21\n"),
            (array_input([5, -100, 6]), "11\n"),
            (array_input([10**9] * 10000), "5000000000000\n"),
            (array_input(range(1, 10001)), "25005000\n"),
        ),
        ["动态规划", "状态转移"],
        "普及+/提高-",
    ),
    make_problem(
        "DEMO-022",
        "代币兑换",
        "有 n 种正整数面值的代币，每种数量不限。希望恰好凑出金额 a，求最少使用的代币数量。无法凑出时输出 -1；金额为 0 时不需要代币。",
        "第一行 n a；第二行 n 个不同的正整数面值。",
        "输出最少代币数量，或 -1。",
        "1 ≤ n ≤ 20；0 ≤ a ≤ 10000；1 ≤ 面值 ≤ 100。",
        cases(
            ("3 6\n1 3 4\n", "2\n"),
            ("2 7\n2 4\n", "-1\n"),
            ("1 0\n5\n", "0\n"),
            ("1 9999\n1\n", "9999\n"),
            ("1 49\n7\n", "7\n"),
            ("3 27\n2 5 10\n", "4\n"),
            ("4 63\n1 5 10 25\n", "6\n"),
            ("3 10000\n1 4 9\n", "1112\n"),
        ),
        ["动态规划", "完全背包"],
        "普及+/提高-",
    ),
    make_problem(
        "DEMO-023",
        "营地联络网",
        "n 个营地之间有若干条双向道路。如果两个营地之间可以通过一条或多条道路到达，就属于同一联络区。孤立营地也单独形成一个联络区。求联络区数量。",
        "第一行 n m；接下来 m 行，每行 u v 表示一条双向道路。",
        "输出无向图的连通分量数。",
        "1 ≤ n ≤ 100000；0 ≤ m ≤ 200000；1 ≤ u,v ≤ n，允许重复边和自环。",
        cases(
            ("4 2\n1 2\n3 4\n", "2\n"),
            ("3 0\n", "3\n"),
            ("1 0\n", "1\n"),
            ("1 1\n1 1\n", "1\n"),
            ("4 3\n1 2\n2 3\n3 1\n", "2\n"),
            ("4 3\n1 2\n1 2\n3 3\n", "3\n"),
            ("10000 9999\n" + "".join(f"{i} {i+1}\n" for i in range(1, 10000)), "1\n"),
            ("10000 0\n", "10000\n"),
        ),
        ["图论", "并查集", "连通分量"],
        "普及+/提高-",
    ),
    make_problem(
        "DEMO-024",
        "方格送信",
        "地图是 n 行 m 列的方格，点号 . 表示可通行，井号 # 表示障碍。"
        "从左上角走到右下角，每步只能向上、下、左、右移动一格，不能越界或进入障碍。"
        "求最少步数；起点或终点被阻塞、或无法到达时输出 -1。",
        "第一行 n m；接下来 n 行，每行 m 个字符，仅含 . 和 #，不含空格。",
        "输出最少移动步数；不可达时输出 -1。起终点为同一个可通行格时输出 0。",
        "1 ≤ n,m ≤ 500。",
        cases(
            ("3 4\n....\n.##.\n....\n", "5\n"),
            ("2 2\n.#\n#.\n", "-1\n"),
            ("1 1\n.\n", "0\n"),
            ("1 1\n#\n", "-1\n"),
            ("1 5\n.....\n", "4\n"),
            ("2 2\n..\n.#\n", "-1\n"),
            ("5 5\n.....\n####.\n.....\n.####\n.....\n", "16\n"),
            ("500 500\n" + ("." * 500 + "\n") * 500, "998\n"),
        ),
        ["图论", "广度优先搜索", "最短路", "队列"],
        "普及+/提高-",
    ),
]


def english_statement(title, description, inputs, outputs, constraints):
    return {
        "title": title,
        "description": description,
        "input_description": inputs,
        "output_description": outputs,
        "constraints": constraints,
        "hint": "Start with the samples, then check the boundary cases.",
    }


DEMO_ENGLISH = {
    "DEMO-001": english_statement(
        "Two Ledger Entries",
        "Two integer amounts were added to a ledger. Income is positive and spending is "
        "negative. Compute their total.",
        "One line contains two integers a and b separated by a space.",
        "Print one integer: a + b.",
        "−10⁹ ≤ a, b ≤ 10⁹.",
    ),
    "DEMO-002": english_statement(
        "Consecutive Sunny Days",
        "A weather record uses 1 for a sunny day and 0 otherwise. Given records for n "
        "consecutive days, find the longest run of sunny days.",
        "The first line contains n. The second line contains n integers, each 0 or 1.",
        "Print the length of the longest consecutive run of 1s, or 0 if there is none.",
        "1 ≤ n ≤ 100000.",
    ),
    "DEMO-003": english_statement(
        "Reading Plan",
        "Each book has an integer page count. For every query, find the total pages from "
        "book l through book r, inclusive.",
        "The first line contains n and q. The second line contains n non-negative page "
        "counts. Each of the next q lines contains l and r; indexing starts at 1.",
        "Print the total for each query on its own line.",
        "1 ≤ n, q ≤ 100000; 0 ≤ pages ≤ 10⁹; 1 ≤ l ≤ r ≤ n.",
    ),
    "DEMO-004": english_statement(
        "Task Dependencies",
        "A task may require another task to finish first. Determine whether the given "
        "dependencies contain a cycle. An edge u → v means u must finish before v; no "
        "real threads need to be started.",
        "The first line contains n and m. Each of the next m lines contains a directed "
        "dependency u v.",
        "Print YES if a directed cycle exists; otherwise print NO.",
        "1 ≤ n ≤ 100000; 0 ≤ m ≤ 200000; 1 ≤ u, v ≤ n. Self-loops and duplicate edges "
        "are allowed.",
    ),
    "DEMO-005": english_statement(
        "Packing the Warehouse",
        "A warehouse has n items and each box can hold at most k items. Items cannot be "
        "split, and the last box may be partly filled. Find the minimum number of boxes; "
        "zero items require zero boxes.",
        "One line contains two integers n and k.",
        "Print the minimum number of boxes.",
        "0 ≤ n ≤ 10¹⁸; 1 ≤ k ≤ 10⁹.",
    ),
    "DEMO-006": english_statement(
        "Training Grade",
        "A training score is an integer s. Scores of at least 90 receive A, 75 through 89 "
        "receive B, 60 through 74 receive C, and lower scores receive D. Determine the grade.",
        "One line contains the integer s.",
        "Print one uppercase letter: A, B, C, or D.",
        "0 ≤ s ≤ 100.",
    ),
    "DEMO-007": english_statement(
        "ID Checksum",
        "The checksum of a non-negative integer ID is the sum of its decimal digits. For "
        "example, the checksum of 5030 is 5+0+3+0=8. Compute the checksum of the given ID.",
        "One line contains a non-negative integer n without unnecessary leading zeros.",
        "Print the sum of its decimal digits.",
        "0 ≤ n ≤ 10¹⁸.",
    ),
    "DEMO-008": english_statement(
        "Trailing Zeros of a Factorial",
        "Define n! as the product of the integers from 1 through n, with 0!=1. Find the "
        "number of consecutive zeros at the end of the decimal representation of n!. Do "
        "not print the factorial itself.",
        "One line contains the integer n.",
        "Print the number of trailing zeros.",
        "0 ≤ n ≤ 10⁹.",
    ),
    "DEMO-009": english_statement(
        "Mirror Passphrase",
        "A passphrase contains only lowercase English letters. It is a mirror passphrase "
        "when it reads exactly the same from left to right and from right to left. Decide "
        "whether the given passphrase qualifies.",
        "One line contains a non-empty string s.",
        "Print YES for a mirror passphrase; otherwise print NO.",
        "1 ≤ |s| ≤ 100000; every character is between a and z.",
    ),
    "DEMO-010": english_statement(
        "Most Frequent Letter",
        "Count each letter in a lowercase string. Select a letter with the highest count; "
        "if several tie, select the alphabetically earliest one.",
        "One line contains a non-empty lowercase string s.",
        "Print the selected letter and its count, separated by one space.",
        "1 ≤ |s| ≤ 100000; every character is between a and z.",
    ),
    "DEMO-011": english_statement(
        "Sign Run Compression",
        "A lowercase string records signs along a route. Replace each maximal run of the "
        "same letter with that letter followed by the run length: aaabb becomes a3 b2. "
        "A run of length one must still include the digit 1.",
        "One line contains a non-empty lowercase string s.",
        "Print the letter and length of every run from left to right, separating adjacent "
        "runs with one space.",
        "1 ≤ |s| ≤ 100000; every character is between a and z.",
    ),
    "DEMO-012": english_statement(
        "Second Distinct Height",
        "Given n observed heights, repeated values count as one distinct height. Find the "
        "largest height strictly below the maximum. If fewer than two distinct heights "
        "exist, print NONE.",
        "The first line contains n. The second line contains n integer heights.",
        "Print the second-largest distinct height, or the uppercase word NONE.",
        "1 ≤ n ≤ 100000; −10⁹ ≤ height ≤ 10⁹.",
    ),
    "DEMO-013": english_statement(
        "Circular Display Board",
        "A display board contains n integers in order. One right rotation moves the last "
        "integer to the front and shifts all others one position right. Find the order "
        "after k consecutive right rotations.",
        "The first line contains n and k. The second line contains n integers.",
        "Print the n integers after the rotations, separated by spaces.",
        "1 ≤ n ≤ 100000; 0 ≤ k ≤ 10¹⁸; each value has absolute value at most 10⁹.",
    ),
    "DEMO-014": english_statement(
        "Morning Run Ranking",
        "The n students are numbered 1 through n in input order and each has a training "
        "score. Rank them by decreasing score; ties are broken by smaller student number.",
        "The first line contains n. The second line contains n non-negative scores.",
        "Print the student numbers in ranking order, separated by spaces.",
        "1 ≤ n ≤ 100000; 0 ≤ score ≤ 10⁹.",
    ),
    "DEMO-015": english_statement(
        "Inspection Segments",
        "There are n closed intervals on a number line. Merge intersecting intervals; "
        "sharing an endpoint counts as intersection. After all merges, find the number of "
        "disjoint segments. Integer intervals that are merely adjacent without sharing a "
        "point are not merged.",
        "The first line contains n. Each of the next n lines contains l and r for the "
        "closed interval [l,r].",
        "Print the number of segments after merging.",
        "1 ≤ n ≤ 100000; −10⁹ ≤ l ≤ r ≤ 10⁹.",
    ),
    "DEMO-016": english_statement(
        "Bookshelf Position",
        "Book IDs are in non-decreasing order and may repeat. For each target x, find the "
        "first position whose ID is at least x. Positions start at 1; return n+1 if no "
        "such position exists.",
        "The first line contains n and q. The second line contains n sorted integers. Each "
        "of the next q lines contains one target x.",
        "Print the position for each query on its own line.",
        "1 ≤ n, q ≤ 100000; every ID and x has absolute value at most 10⁹.",
    ),
    "DEMO-017": english_statement(
        "Moving Piles",
        "A warehouse has n piles and pile i contains aᵢ items. At a positive integer speed "
        "k, each pile separately takes ceil(aᵢ/k) whole hours; leftover capacity from "
        "different piles cannot be combined in one hour. Find the minimum speed that "
        "finishes every pile within h hours.",
        "The first line contains n and h. The second line contains n positive integers aᵢ.",
        "Print the minimum positive integer speed k.",
        "1 ≤ n ≤ 10000; n ≤ h ≤ 10¹⁸; 1 ≤ aᵢ ≤ 10⁹.",
    ),
    "DEMO-018": english_statement(
        "Bracket Checkpoint",
        "A record contains only parentheses, square brackets, and braces. Every opening "
        "bracket must match a closing bracket of the same type in last-in-first-out order, "
        "and no bracket may remain unmatched. Decide whether the whole record is valid.",
        "One line contains a non-empty bracket string s.",
        "Print YES if every bracket is matched; otherwise print NO.",
        "1 ≤ |s| ≤ 100000; characters are limited to ()[]{}.",
    ),
    "DEMO-019": english_statement(
        "Service Counter",
        "A counter uses a first-in-first-out queue that is initially empty. PUSH x adds x "
        "at the back; POP removes and prints the front; FRONT only prints the front. POP "
        "or FRONT on an empty queue prints EMPTY and leaves it empty.",
        "The first line contains q. Each of the next q lines is PUSH x, POP, or FRONT.",
        "Print one line for every POP or FRONT. PUSH prints nothing. If no query or removal "
        "operation occurs, print nothing.",
        "1 ≤ q ≤ 100000; −10⁹ ≤ x ≤ 10⁹.",
    ),
    "DEMO-020": english_statement(
        "Shared Meeting Room",
        "One meeting room receives n bookings, each occupying a half-open interval [s,e). "
        "Select a subset in which no two bookings overlap. A booking may start exactly "
        "when the previous one ends. Find the maximum number that can be accepted.",
        "The first line contains n. Each of the next n lines contains s and e.",
        "Print the maximum number of bookings that can be accepted.",
        "1 ≤ n ≤ 100000; 0 ≤ s < e ≤ 10⁹.",
    ),
    "DEMO-021": english_statement(
        "Alternate-Day Collection",
        "Each of n consecutive days has an integer return. Choose any days to collect, but "
        "never choose two adjacent days. Choosing no day is allowed and gives a return of "
        "zero. Find the maximum total return.",
        "The first line contains n. The second line contains n integer returns in date order.",
        "Print the maximum total return.",
        "1 ≤ n ≤ 100000; each return is between −10⁹ and 10⁹.",
    ),
    "DEMO-022": english_statement(
        "Token Exchange",
        "There are n distinct positive integer token denominations, with unlimited tokens "
        "of each. Make the amount a exactly while using as few tokens as possible. Print "
        "-1 if it is impossible; amount zero needs no tokens.",
        "The first line contains n and a. The second line contains n distinct positive "
        "denominations.",
        "Print the minimum token count, or -1.",
        "1 ≤ n ≤ 20; 0 ≤ a ≤ 10000; 1 ≤ denomination ≤ 100.",
    ),
    "DEMO-023": english_statement(
        "Camp Network",
        "There are undirected roads among n camps. Camps belong to the same communication "
        "region when one can reach the other using one or more roads. An isolated camp "
        "forms its own region. Find the number of regions.",
        "The first line contains n and m. Each of the next m lines contains an undirected "
        "road u v.",
        "Print the number of connected components in the undirected graph.",
        "1 ≤ n ≤ 100000; 0 ≤ m ≤ 200000; 1 ≤ u, v ≤ n. Duplicate edges and self-loops "
        "are allowed.",
    ),
    "DEMO-024": english_statement(
        "Grid Mail Delivery",
        "A map is an n by m grid. A dot . is passable and # is blocked. Move from the "
        "top-left cell to the bottom-right cell, one cell up, down, left, or right at a "
        "time, without leaving the grid or entering an obstacle. Find the fewest steps. "
        "Print -1 if either endpoint is blocked or the destination is unreachable.",
        "The first line contains n and m. Each of the next n lines contains m characters, "
        "only . and #, with no spaces.",
        "Print the minimum number of moves, or -1 if unreachable. Print 0 when the start "
        "and destination are the same passable cell.",
        "1 ≤ n, m ≤ 500.",
    ),
}

for _problem in DEMO_PROBLEMS:
    _problem["translations"] = {"en": DEMO_ENGLISH[_problem["id"]]}
del _problem


# These are original reference programs, not hidden tests or imported solutions.
SEED_SOLUTIONS = {
    "DEMO-001": "a, b = map(int, input().split())\nprint(a + b)\n",
    "DEMO-002": """
        import sys
        data = list(map(int, sys.stdin.buffer.read().split()))
        best = current = 0
        for value in data[1:]:
            current = current + 1 if value else 0
            best = max(best, current)
        print(best)
    """,
    "DEMO-003": """
        import sys
        data = iter(map(int, sys.stdin.buffer.read().split()))
        n, q = next(data), next(data)
        prefix = [0]
        for _ in range(n):
            prefix.append(prefix[-1] + next(data))
        for _ in range(q):
            left, right = next(data), next(data)
            print(prefix[right] - prefix[left - 1])
    """,
    "DEMO-004": """
        import sys
        from collections import deque
        data = iter(map(int, sys.stdin.buffer.read().split()))
        n, m = next(data), next(data)
        edges = [[] for _ in range(n)]
        degree = [0] * n
        for _ in range(m):
            u, v = next(data) - 1, next(data) - 1
            edges[u].append(v)
            degree[v] += 1
        queue = deque(i for i in range(n) if degree[i] == 0)
        visited = 0
        while queue:
            u = queue.popleft()
            visited += 1
            for v in edges[u]:
                degree[v] -= 1
                if degree[v] == 0:
                    queue.append(v)
        print('YES' if visited != n else 'NO')
    """,
    "DEMO-005": "n, k = map(int, input().split())\nprint((n + k - 1) // k)\n",
    "DEMO-006": (
        "s = int(input())\n"
        "print('A' if s >= 90 else 'B' if s >= 75 else 'C' if s >= 60 else 'D')\n"
    ),
    "DEMO-007": "print(sum(map(int, input().strip())))\n",
    "DEMO-008": """
        n = int(input())
        answer = 0
        while n:
            n //= 5
            answer += n
        print(answer)
    """,
    "DEMO-009": "s = input().strip()\nprint('YES' if s == s[::-1] else 'NO')\n",
    "DEMO-010": """
        from collections import Counter
        counts = Counter(input().strip())
        best = min(counts, key=lambda letter: (-counts[letter], letter))
        print(best, counts[best])
    """,
    "DEMO-011": """
        from itertools import groupby
        groups = groupby(input().strip())
        print(' '.join(letter + str(sum(1 for _ in group)) for letter, group in groups))
    """,
    "DEMO-012": """
        import sys
        values = sorted(set(map(int, sys.stdin.buffer.read().split()[1:])))
        print(values[-2] if len(values) > 1 else 'NONE')
    """,
    "DEMO-013": """
        import sys
        data = list(map(int, sys.stdin.buffer.read().split()))
        n, k = data[:2]
        values = data[2:]
        k %= n
        print(*(values[-k:] + values[:-k] if k else values))
    """,
    "DEMO-014": """
        import sys
        scores = list(map(int, sys.stdin.buffer.read().split()))[1:]
        print(*sorted(range(1, len(scores) + 1), key=lambda i: (-scores[i - 1], i)))
    """,
    "DEMO-015": """
        import sys
        data = iter(map(int, sys.stdin.buffer.read().split()))
        intervals = sorted((next(data), next(data)) for _ in range(next(data)))
        answer = 0
        end = None
        for left, right in intervals:
            if end is None or left > end:
                answer += 1
                end = right
            else:
                end = max(end, right)
        print(answer)
    """,
    "DEMO-016": """
        import sys
        from bisect import bisect_left
        data = list(map(int, sys.stdin.buffer.read().split()))
        n, q = data[:2]
        values = data[2:2+n]
        for target in data[2+n:]:
            print(bisect_left(values, target) + 1)
    """,
    "DEMO-017": """
        import sys
        data = list(map(int, sys.stdin.buffer.read().split()))
        n, hours = data[:2]
        piles = data[2:]
        low, high = 1, max(piles)
        while low < high:
            middle = (low + high) // 2
            if sum((pile + middle - 1) // middle for pile in piles) <= hours:
                high = middle
            else:
                low = middle + 1
        print(low)
    """,
    "DEMO-018": """
        stack = []
        opening = {')': '(', ']': '[', '}': '{'}
        valid = True
        for letter in input().strip():
            if letter in '([{':
                stack.append(letter)
            elif not stack or stack.pop() != opening[letter]:
                valid = False
                break
        print('YES' if valid and not stack else 'NO')
    """,
    "DEMO-019": """
        import sys
        from collections import deque
        queue = deque()
        for command in sys.stdin.buffer.read().decode().splitlines()[1:]:
            parts = command.split()
            if parts[0] == 'PUSH':
                queue.append(int(parts[1]))
            elif not queue:
                print('EMPTY')
            elif parts[0] == 'POP':
                print(queue.popleft())
            else:
                print(queue[0])
    """,
    "DEMO-020": """
        import sys
        data = iter(map(int, sys.stdin.buffer.read().split()))
        intervals = [(next(data), next(data)) for _ in range(next(data))]
        intervals.sort(key=lambda interval: interval[1])
        end = -1
        answer = 0
        for start, finish in intervals:
            if start >= end:
                answer += 1
                end = finish
        print(answer)
    """,
    "DEMO-021": """
        import sys
        previous = current = 0
        for value in map(int, sys.stdin.buffer.read().split()[1:]):
            previous, current = current, max(current, previous + value)
        print(current)
    """,
    "DEMO-022": """
        import sys
        data = list(map(int, sys.stdin.buffer.read().split()))
        n, amount = data[:2]
        coins = data[2:]
        dp = [0] + [amount + 1] * amount
        for total in range(1, amount + 1):
            for coin in coins:
                if coin <= total:
                    dp[total] = min(dp[total], dp[total - coin] + 1)
        print(dp[amount] if dp[amount] <= amount else -1)
    """,
    "DEMO-023": """
        import sys
        data = iter(map(int, sys.stdin.buffer.read().split()))
        n, m = next(data), next(data)
        parent = list(range(n))
        size = [1] * n
        def find(value):
            while parent[value] != value:
                parent[value] = parent[parent[value]]
                value = parent[value]
            return value
        answer = n
        for _ in range(m):
            u, v = find(next(data) - 1), find(next(data) - 1)
            if u != v:
                if size[u] < size[v]:
                    u, v = v, u
                parent[v] = u
                size[u] += size[v]
                answer -= 1
        print(answer)
    """,
    "DEMO-024": """
        import sys
        from collections import deque
        n, m = map(int, sys.stdin.buffer.readline().split())
        grid = [sys.stdin.buffer.readline().strip() for _ in range(n)]
        distance = [[-1] * m for _ in range(n)]
        queue = deque()
        if grid[0][0] == 46 and grid[-1][-1] == 46:
            queue.append((0, 0))
            distance[0][0] = 0
        while queue:
            row, col = queue.popleft()
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                r, c = row + dr, col + dc
                if 0 <= r < n and 0 <= c < m and grid[r][c] == 46 and distance[r][c] == -1:
                    distance[r][c] = distance[row][col] + 1
                    queue.append((r, c))
        print(distance[-1][-1])
    """,
}
SEED_SOLUTIONS = {key: dedent(code).strip() + "\n" for key, code in SEED_SOLUTIONS.items()}
