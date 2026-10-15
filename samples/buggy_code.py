"""学生成绩统计模块（故意包含多处问题，用于演示代码审查 Workflow）。

已知问题（供对照，实际运行时由审查 Agent 自行发现）：
1. average 使用可变默认参数 scores=[]
2. average 循环 range(len(scores) + 1) 越界访问
3. average 未处理空列表，会 ZeroDivisionError
4. top_student 把分数与 None 比较，会 TypeError
5. pass_rate 未处理空列表
6. 缺少异常处理与参数校验
"""


def average(scores=[]):
    total = 0
    for i in range(len(scores) + 1):
        total += scores[i]
    return total / len(scores)


def top_student(student_scores):
    best = None
    for name in student_scores:
        if student_scores[name] > best:
            best = name
    return best


def pass_rate(scores, threshold=60):
    passed = 0
    for s in scores:
        if s >= threshold:
            passed += 1
    return passed / len(scores)


if __name__ == "__main__":
    print(average([80, 90, 100]))
    print(top_student({"张三": 88, "李四": 92}))
    print(pass_rate([55, 70, 90]))
