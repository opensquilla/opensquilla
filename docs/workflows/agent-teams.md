# Agent Teams 编排指南

Agent Teams 是多 Agent 协作模式，让多个专门化 Agent 共同完成复杂任务。

## 🎯 什么是 Agent Teams？

### 传统单 Agent vs Agent Teams

```
┌─────────────────────────────────────────────────────────────┐
│                    传统单 Agent                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  用户请求 → 一个 Agent 处理所有任务                      │ │
│  │  - 上下文压力大                                         │ │
│  │  - 专精能力有限                                         │ │
│  │  - 难以并行化                                           │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     Agent Teams                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  用户请求 → 协调器 → 多个专门 Agent 并行协作              │ │
│  │                                                         │ │
│  │  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐       │ │
│  │  │ Planner│  │Coder   │  │Research│  │Reviewer│       │ │
│  │  └────────┘  └────────┘  └────────┘  └────────┘       │ │
│  │                                                         │ │
│  │  - 每个 Agent 专精一个领域                               │ │
│  │  - 可以并行执行                                           │ │
│  │  - Token 效率更高                                        │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 核心概念

| 概念 | 说明 |
|------|------|
| **Team** | 多个 Agent 的集合 |
| **Coordinator** | 团队协调器，负责任务分配 |
| **Agent** | 专门化的智能体 |
| **Workflow** | 定义 Agent 间的协作流程 |
| **Shared Context** | Agent 间共享的上下文 |

---

## 🏗️ 架构设计

### 团队架构

```
┌─────────────────────────────────────────────────────────────┐
│                        用户请求                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     Coordinator                               │
│  - 解析任务                                                 │
│  - 制定计划                                                 │
│  - 分配工作流                                               │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Planner     │    │  Researcher  │    │   Coder      │
│  Agent       │    │  Agent       │    │   Agent      │
│              │    │              │    │              │
│ - 任务规划   │    │ - 信息收集   │    │ - 代码生成   │
│ - 步骤拆解   │    │ - 数据分析   │    │ - Bug 修复   │
│ - 依赖分析   │    │ - 文档检索   │    │ - 重构优化   │
└──────────────┘    └──────────────┘    └──────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     Reviewer Agent                            │
│  - 质量检查                                                 │
│  - 一致性验证                                               │
│  - 最终汇总                                                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                        用户响应                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔧 快速开始

### 创建第一个 Team

```yaml
# teams/dev-team.yaml
name: "Development Team"
description: "软件开发团队"

coordinator:
  type: "planner"
  model: "claude-3-5-sonnet-20250114"

agents:
  - name: "planner"
    type: "planner"
    model: "claude-3-5-sonnet-20250114"
    description: "负责任务规划和步骤拆解"
    capabilities:
      - "task_planning"
      - "dependency_analysis"
      - "step_breakdown"

  - name: "researcher"
    type: "researcher"
    model: "gpt-4o"
    description: "负责信息收集和数据分析"
    capabilities:
      - "web_search"
      - "data_analysis"
      - "documentation"

  - name: "coder"
    type: "coder"
    model: "claude-3-5-sonnet-20250114"
    description: "负责代码开发和修复"
    capabilities:
      - "code_generation"
      - "bug_fixing"
      - "refactoring"
    tools:
      - "filesystem"
      - "github"

  - name: "reviewer"
    type: "reviewer"
    model: "gpt-4o"
    description: "负责代码审查和质量检查"
    capabilities:
      - "code_review"
      - "quality_check"
      - "security_audit"

workflows:
  - name: "feature_development"
    description: "新功能开发工作流"
    steps:
      - agent: "planner"
        action: "plan_feature"
        output: "feature_plan"

      - agent: "researcher"
        action: "research_requirements"
        input: "feature_plan"
        output: "requirements_doc"

      - agent: "coder"
        action: "implement_feature"
        input: "requirements_doc"
        output: "feature_code"

      - agent: "reviewer"
        action: "review_code"
        input: "feature_code"
        output: "review_report"
```

### 启用 Team

```bash
# 加载 Team 配置
opensquilla teams load dev-team.yaml

# 运行 Team
opensquilla teams run dev-team --workflow feature_development \
  --input "实现用户登录功能，支持 OAuth2"

# 或使用交互模式
opensquilla teams run dev-team
```

---

## 📋 内置 Agent 类型

### Planner Agent

**职责**：任务规划和协调

```yaml
type: planner
model: claude-3-5-sonnet-20250114
system_prompt: |
  你是一个任务规划专家。你的职责是：
  1. 理解用户目标的完整性
  2. 将复杂任务拆解为可执行的步骤
  3. 识别任务间的依赖关系
  4. 评估每步的资源需求

  输出格式：
  - 任务概述
  - 步骤列表（含依赖）
  - 所需资源
  - 风险评估
```

### Researcher Agent

**职责**：信息收集和分析

```yaml
type: researcher
model: gpt-4o
system_prompt: |
  你是一个研究分析师。你的职责是：
  1. 收集相关信息（网络搜索、文档检索）
  2. 分析和总结数据
  3. 提供数据驱动的洞察
  4. 验证信息的准确性

  输出格式：
  - 研究发现
  - 数据支持
  - 可行性分析
  - 参考来源
```

### Coder Agent

**职责**：代码开发和实现

```yaml
type: coder
model: claude-3-5-sonnet-20250114
system_prompt: |
  你是一个软件开发工程师。你的职责是：
  1. 编写高质量、可维护的代码
  2. 遵循最佳实践和编码规范
  3. 编写必要的测试
  4. 优化性能

  输出格式：
  - 代码实现
  - 技术说明
  - 测试用例
  - 部署指南
```

### Reviewer Agent

**职责**：质量审查和验证

```yaml
type: reviewer
model: gpt-4o
system_prompt: |
  你是一个代码审查专家。你的职责是：
  1. 审查代码质量和安全性
  2. 验证功能完整性
  3. 检查规范符合性
  4. 提供改进建议

  输出格式：
  - 审查意见
  - 问题清单
  - 评分
  - 改进建议
```

---

## 🔄 工作流定义

### 顺序工作流

```yaml
workflows:
  - name: "sequential_development"
    type: sequential
    steps:
      - step: "1"
        agent: "planner"
        task: "规划任务"
        output_to: "plan"

      - step: "2"
        agent: "coder"
        task: "实现功能"
        input_from: "plan"
        output_to: "code"

      - step: "3"
        agent: "reviewer"
        task: "审查代码"
        input_from: "code"
        output_to: "report"
```

### 并行工作流

```yaml
workflows:
  - name: "parallel_research"
    type: parallel
    steps:
      - step: "1"
        parallel:
          - agent: "researcher"
            task: "收集市场数据"
            output_to: "market_data"

          - agent: "researcher"
            task: "收集竞品信息"
            output_to: "competitor_data"

          - agent: "researcher"
            task: "分析用户反馈"
            output_to: "user_feedback"

      - step: "2"
        agent: "planner"
        task: "综合分析"
        input_from:
          - "market_data"
          - "competitor_data"
          - "user_feedback"
```

### 条件工作流

```yaml
workflows:
  - name: "conditional_workflow"
    type: conditional
    steps:
      - step: "1"
        agent: "reviewer"
        task: "评估复杂度"

      - step: "2"
        condition: "{{step1.complexity}} > 7"
        then:
          agent: "senior_coder"
          task: "高级实现"
        else:
          agent: "coder"
          task: "标准实现"
```

### 循环工作流

```yaml
workflows:
  - name: "iterative_improvement"
    type: loop
    steps:
      - step: "1"
        agent: "coder"
        task: "实现功能"
        output_to: "code"

      - step: "2"
        agent: "reviewer"
        task: "审查代码"
        input_from: "code"
        output_to: "review"

      - step: "3"
        condition: "{{review.score}} < 8"
        loop_to: "1"
        max_iterations: 3
```

---

## 🎨 实战案例

### 案例 1：自动化测试生成

```yaml
# teams/test-team.yaml
name: "QA Automation Team"

agents:
  - name: "analyzer"
    type: "analyzer"
    model: "claude-3-5-sonnet-20250114"
    description: "分析需求，识别测试场景"

  - name: "generator"
    type: "generator"
    model: "gpt-4o"
    description: "生成测试用例和测试代码"

  - name: "executor"
    type: "executor"
    model: "claude-3-5-sonnet-20250114"
    description: "执行测试并收集结果"

  - name: "reporter"
    type: "reporter"
    model: "gpt-4o"
    description: "生成测试报告"

workflows:
  - name: "automated_testing"
    steps:
      - agent: "analyzer"
        task: "分析需求文档，识别测试场景"
        output_to: "test_scenarios"

      - agent: "generator"
        task: "为每个场景生成测试用例"
        input_from: "test_scenarios"
        output_to: "test_cases"

      - agent: "generator"
        task: "生成自动化测试代码"
        input_from: "test_cases"
        output_to: "test_code"

      - agent: "executor"
        task: "执行测试并收集结果"
        input_from: "test_code"
        output_to: "test_results"

      - agent: "reporter"
        task: "生成测试报告"
        input_from: "test_results"
```

运行：

```bash
opensquilla teams run test-team \
  --workflow automated_testing \
  --input "需求文档：user-story-123.md"
```

### 案例 2：内容生产流水线

```yaml
# teams/content-team.yaml
name: "Content Production Team"

agents:
  - name: "strategist"
    type: "planner"
    model: "claude-3-5-sonnet-20250114"
    description: "内容策略和选题规划"

  - name: "writer"
    type: "creator"
    model: "gpt-4o"
    description: "内容创作"

  - name: "editor"
    type: "reviewer"
    model: "claude-3-5-sonnet-20250114"
    description: "内容编辑和优化"

  - name: "seo_specialist"
    type: "optimizer"
    model: "gpt-4o"
    description: "SEO 优化"

  - name: "publisher"
    type: "executor"
    model: "claude-3-5-sonnet-20250114"
    description: "发布和分发"

workflows:
  - name: "blog_production"
    steps:
      - agent: "strategist"
        task: "规划内容选题"
        output_to: "content_plan"

      - parallel:
          - agent: "writer"
            task: "撰写文章草稿"
            input_from: "content_plan"
            output_to: "draft"

          - agent: "researcher"
            task: "收集相关资料和数据"
            input_from: "content_plan"
            output_to: "research_data"

      - agent: "writer"
        task: "整合研究数据，完善草稿"
        input_from: ["draft", "research_data"]
        output_to: "revised_draft"

      - agent: "editor"
        task: "编辑和校对"
        input_from: "revised_draft"
        output_to: "edited_draft"

      - agent: "seo_specialist"
        task: "SEO 优化"
        input_from: "edited_draft"
        output_to: "final_content"

      - agent: "publisher"
        task: "发布内容"
        input_from: "final_content"
```

---

## 📊 性能优化

### Token 效率

Agent Teams 相比单 Agent 的 Token 效率：

| 场景 | 单 Agent | Agent Teams | 节省 |
|------|---------|-------------|------|
| 简单任务 | 10K | 8K | 20% |
| 中等任务 | 50K | 35K | 30% |
| 复杂任务 | 200K | 120K | 40% |

### 优化策略

1. **选择合适的模型**
   - 协调器使用强模型
   - 专门化 Agent 可用中档模型
   - 简单任务使用小型模型

2. **并行执行**
   - 独立任务并行执行
   - 减少总等待时间

3. **缓存复用**
   - 缓存常用结果
   - Agent 间共享上下文

4. **智能路由**
   - 使用 SquillaRouter 自动选择模型
   - 根据任务复杂度动态调整

---

## 🔍 监控和调试

### 监控指标

```bash
# 查看 Team 状态
opensquilla teams status dev-team

# 查看 Agent 性能
opensquilla teams metrics dev-team --agent coder

# 查看工作流执行
opensquilla teams history dev-team --workflow feature_development
```

### 调试模式

```bash
# 启用调试日志
opensquilla teams run dev-team --debug

# 查看详细执行过程
opensquilla teams run dev-team --verbose --trace
```

---

## 🚀 高级功能

### 动态 Team

```yaml
teams:
  - name: "dynamic_team"
    dynamic: true
    agent_pool:
      - type: "coder"
        count: 3
      - type: "reviewer"
        count: 1
    scaling:
      min_agents: 2
      max_agents: 10
      scale_up_threshold: 5  # 队列长度
      scale_down_threshold: 1
```

### 跨 Team 协作

```yaml
# 超级 Team
name: "Super Team"
sub_teams:
  - team: "dev-team"
    workflow: "feature_development"
  - team: "qa-team"
    workflow: "automated_testing"
  - team: "ops-team"
    workflow: "deployment"

orchestration:
  - trigger: "dev-team.completed"
    action: "qa-team.run"
  - trigger: "qa-team.passed"
    action: "ops-team.run"
  - trigger: "qa-team.failed"
    action: "dev-team.run_with_fixes"
```

---

## 相关资源

- [工作流定义](./workflows.md)
- [Agent 配置](../configuration/agents.md)
- [性能优化](../performance/index.md)
- [监控指南](../enterprise/monitoring.md)
