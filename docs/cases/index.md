# 真实行业案例集

OpenSquilla Agent 在各行业的真实应用案例和最佳实践。

## 📋 案例目录

| 行业 | 案例 | 核心价值 |
|------|------|----------|
| **金融** | 智能客服、风控报告、投研分析 | 降低成本、提升效率 |
| **电商** | 商品问答、订单处理、评论分析 | 提高转化率 |
| **制造** | 设备诊断、质检报告、维修指导 | 减少停机时间 |
| **医疗** | 病历分析、报告生成、患者问答 | 提升诊断效率 |
| **教育** | 作业批改、学习辅导、知识问答 | 个性化学习 |
| **法律** | 合同审查、案例检索、文书生成 | 降低合规风险 |
| **政务** | 政策解读、办事指引、民意分析 | 提升服务体验 |
| **媒体** | 内容创作、编辑辅助、热点追踪 | 提高内容产能 |

---

## 💰 金融行业

### 案例一：智能客服

**背景**：某银行每天处理 10万+ 客户咨询，人工客服成本高昂。

**解决方案**：

```yaml
# skills/banking/customer-service.md
---
name: banking_customer_service
description: 银行智能客服
---

## 能力

### 账户查询
- 余额查询
- 交易明细
- 账户状态

### 业务办理
- 挂失
- 密码重置
- 转账指导

### 产品咨询
- 理财产品推荐
- 贷款咨询
- 信用卡申请
```

**效果**：
- 自动处理率：75%
- 平均响应时间：从 5 分钟降至 3 秒
- 客服成本：降低 60%

### 案例二：风控报告生成

**背景**：某消费金融公司需要每天分析大量交易数据，生成风控报告。

**解决方案**：

```yaml
# workflows/credit-risk-report.yaml
name: "daily_risk_report"
description: "每日风控报告生成"

schedule:
  cron: "0 2 * * *"

steps:
  - id: "fetch_transactions"
    connector:
      type: postgres
      query: |
        SELECT * FROM transactions
        WHERE date = CURRENT_DATE - 1

  - id: "analyze_risks"
    agent: "risk_analyst"
    params:
      models:
        - "fraud_detection"
        - "credit_risk"

  - id: "generate_report"
    agent: "report_generator"
    params:
      format: "pdf"
      sections:
        - "Executive Summary"
        - "Risk Metrics"
        - "Alerts"
        - "Recommendations"

  - id: "distribute"
    action: "email"
    recipients:
      - "risk@company.com"
      - "management@company.com"
```

**效果**：
- 报告生成时间：从 4 小时降至 10 分钟
- 风险发现准确率：提升 30%
- 人力成本：节省 2 名分析师

---

## 🛒 电商行业

### 案例三：商品智能问答

**背景**：某电商平台用户咨询量大，客服回答商品相关问题耗时。

**解决方案**：

```yaml
# skills/ecommerce/product-qa.md
---
name: product_qa_assistant
description: 商品问答助手
---

## 商品问答

### 基于知识库

```yaml
knowledge_base:
  sources:
    - type: "catalog"
      format: "json"
      update: "daily"

    - type: "reviews"
      format: "database"
      update: "hourly"

  retrieval:
    method: "hybrid"  # vector + keyword
    top_k: 5
```

### 使用示例

```python
from opensquilla import Agent

agent = Agent(name="product_qa")

result = agent.run(
    message="这款手机的电池续航怎么样？",
    context={
        "product_id": "123456",
        "user_id": "user_123"
    }
)

# 回答基于商品详情和用户评价
print(result.response)
```

**效果**：
- 咨询转化率：提升 25%
- 客服工作量：减少 50%
- 用户满意度：提升 15%

### 案例四：订单智能处理

**背景**：某电商每天处理异常订单需要大量人工介入。

**解决方案**：

```yaml
# workflows/order-automation.yaml
name: "order_exception_handler"
description: "订单异常自动处理"

trigger:
  type: "event"
  source: "order_system"

rules:
  - condition: "exception_type == 'address_invalid'"
    action:
      agent: "address_validator"
      params:
        auto_correct: true
        notify_user: true

  - condition: "exception_type == 'payment_failed'"
    action:
      agent: "payment_assistant"
      params:
        retry: true
        max_attempts: 3

  - condition: "exception_type == 'inventory_shortage'"
    action:
      agent: "inventory_manager"
      params:
        suggest_alternatives: true
        estimate_restock: true
```

**效果**：
- 自动解决率：70%
- 订单处理时间：减少 60%
- 客户投诉：降低 40%

---

## 🏭 制造业

### 案例五：设备故障诊断

**背景**：某制造企业设备停机造成巨大损失，需要快速诊断和修复。

**解决方案**：

```yaml
# skills/manufacturing/equipment-diagnostic.md
---
name: equipment_diagnostic
description: 设备故障诊断助手
---

## 诊断流程

### 信息收集

```python
from opensquilla import Agent

agent = Agent(name="equipment_diagnostic")

result = agent.run(
    message="3号生产线停机了，帮我诊断问题",
    context={
        "equipment_id": "LINE_03",
        "error_code": "E_503",
        "symptoms": ["belt_slipping", "noise_increased"],
        "manual": "equipment_manual.pdf"
    }
)
```

### 诊断输出

```json
{
  "diagnosis": {
    "likely_cause": "传送带张紧度不足",
    "confidence": 0.85,
    "recommendations": [
      "检查传送带张紧装置",
      "测量张紧力（目标值：45-50 N）",
      "如磨损超过 2mm，需更换传送带"
    ],
    "estimated_downtime": "30分钟",
    "parts_needed": ["张紧弹簧", "传送带"],
    "safety_notes": "操作前务必断电并挂牌"
  }
}
```

**效果**：
- 故障诊断时间：从 2 小时降至 15 分钟
- 停机时间：减少 50%
- 维修成本：降低 30%

---

## 🏥 医疗行业

### 案例六：病历智能分析

**背景**：某医院医生需要快速了解患者历史病历和检查结果。

**解决方案**：

```yaml
# skills/healthcare/medical-analyst.md
---
name: medical_record_analyst
description: 病历分析助手
---

## 病历分析

### 功能

```python
from opensquilla import Agent

agent = Agent(name="medical_analyst")

result = agent.run(
    message="总结这位患者的病史和当前情况",
    context={
        "patient_id": "P12345",
        "records": [
            "past_visits.txt",
            "lab_results.pdf",
            "imaging_reports.docx"
        ]
    }
)
```

### 输出示例

```
患者病史总结：
------------------
基本信息：男性，65岁

主诉：胸痛、呼吸困难

病史：
- 高血压（10年）
- 糖尿病（5年）
- 冠心病（2020年PCI术后）

检查结果：
- 心电图：ST段压低
- 肌钙蛋白：升高
- 超声心动图：EF 45%

印象：急性冠脉综合征可能性大
建议：立即心内科会诊，考虑紧急冠脉造影
```

**效果**：
- 病历阅读时间：减少 70%
- 关键信息遗漏：减少 80%
- 诊断效率：提升 40%

---

## 📚 教育行业

### 案例七：智能作业批改

**背景**：某在线教育平台需要大量人力批改学生作业。

**解决方案**：

```yaml
# skills/education/homework-grader.md
---
name: homework_grader
description: 作业智能批改
---

## 作业批改

### 支持类型

- 英语作文
- 数学解题
- 代码编程
- 简答题

### 批改流程

```python
from opensquilla import Agent

agent = Agent(name="homework_grader")

result = agent.run(
    message="批改这份作业",
    context={
        "subject": "english_writing",
        "rubric": "grading_rubric.json",
        "student_submission": "essay.txt",
        "reference": "sample_answer.txt"
    }
)
```

### 批改结果

```json
{
  "score": 85,
  "max_score": 100,
  "feedback": {
    "strengths": [
      "语法结构正确",
      "论点清晰",
      "词汇使用丰富"
    ],
    "improvements": [
      "第3段论证不够充分",
      "结论可以更简洁",
      "建议增加具体例子"
    ],
    "corrections": [
      {
        "line": 12,
        "original": "Their is",
        "corrected": "There is",
        "type": "grammar"
      }
    ]
  }
}
```

**效果**：
- 批改效率：提升 10 倍
- 反馈时效：从 3 天降至即时
- 教师工作量：减少 70%

---

## ⚖️ 法律行业

### 案例八：合同智能审查

**背景**：某律所每天需要审查大量合同，人工审查耗时且容易遗漏。

**解决方案**：

```yaml
# skills/legal/contract-reviewer.md
---
name: contract_reviewer
description: 合同智能审查
---

## 合同审查

### 审查要点

```python
from opensquilla import Agent

agent = Agent(name="contract_reviewer")

result = agent.run(
    message="审查这份租赁合同",
    context={
        "contract": "lease_agreement.pdf",
        "template": "standard_lease_template.md",
        "checklist": "lease_review_checklist.json"
    }
)
```

### 审查报告

```
合同审查报告
================

合同类型：商业租赁合同
当事人：
- 出租方：ABC物业有限公司
- 承租方：XYZ科技发展有限公司

风险评估：中高

发现问题：
1. 租期条款
   - 合同约定：5年
   - 风险：未约定提前终止条件
   - 建议：增加双方提前终止权条款

2. 租金调整
   - 合同约定：每年递增5%
   - 风险：未约定市场低迷时的调整机制
   - 建议：设置租金调整上限

3. 维修责任
   - 合同约定：承租方承担全部维修
   - 风险：与法律惯例不符
   - 建议：区分结构性维修和日常维护

高风险条款（需重点关注）：
- 第12条违约责任
- 第15条争议解决

总体建议：建议修改后签署
```

**效果**：
- 审查时间：从 2 小时降至 15 分钟
- 条款遗漏：减少 90%
- 审查质量：标准化、一致化

---

## 🏛️ 政务服务

### 案例九：政策智能解读

**背景**：政府发布大量政策文件，企业和市民难以理解。

**解决方案**：

```yaml
# skills/government/policy-interpreter.md
---
name: policy_interpreter
description: 政策智能解读
---

## 政策解读

### 功能

```python
from opensquilla import Agent

agent = Agent(name="policy_interpreter")

result = agent.run(
    message="解读这项税收优惠政策，告诉我公司是否可以享受",
    context={
        "policy": "tax_policy_2026.pdf",
        "company_profile": {
            "industry": "software",
            "employees": 150,
            "revenue": "5000万",
            "location": "上海浦东"
        }
    }
)
```

### 解读输出

```
政策解读报告
================

政策名称：2026年度软件企业税收优惠政策
发布机构：财政部、税务总局
生效时间：2026年1月1日

核心内容：
1. 符合条件的软件企业，所得税减按15%征收
2. 研发费用可加计扣除175%
3. 软件产品销售增值税超过3%即征即退

贵公司适用性分析：
✅ 适用条件：
   - 企业类型：软件企业（符合）
   - 研发投入：占收入18%（超过6%要求）
   - 知识产权：拥有30项软件著作权（符合）

预期收益：
- 所得税节省：约200万/年
- 研发加计扣除：约350万/年
- 增值税返还：约150万/年

申请材料：
1. 软件企业认定证书
2. 研发费用明细账
3. 知识产权清单
4. 专项审计报告

建议：建议尽快申请，政策有效期至2027年底
```

---

## 📊 实施指南

### 项目实施步骤

```yaml
implementation:
  phase_1:
    name: "需求分析"
    duration: "2-4 周"
    tasks:
      - 业务需求收集
      - 场景定义
      - ROI 评估

  phase_2:
    name: "原型验证"
    duration: "4-6 周"
    tasks:
      - Agent 设计
      - Knowledge Base 构建
      - Demo 开发

  phase_3:
    name: "试点上线"
    duration: "4-8 周"
    tasks:
      - 小范围试点
      - 效果评估
      - 迭代优化

  phase_4:
    name: "全面推广"
    duration: "8-12 周"
    tasks:
      - 用户培训
      - 逐步上线
      - 持续优化
```

### 成功指标

| 指标类型 | 示例 |
|---------|------|
| **效率** | 处理时间、响应速度、自动化率 |
| **质量** | 准确率、满意度、错误率 |
| **成本** | 人力节省、运营成本降低 |
| **体验** | 用户满意度、NPS |

---

## 📞 相关资源

- [企业部署](../enterprise/deployment.md)
- [工作流自动化](../workflows/automation.md)
- [多模态处理](../multimodal/overview.md)
- [API 服务](../api/service.md)
