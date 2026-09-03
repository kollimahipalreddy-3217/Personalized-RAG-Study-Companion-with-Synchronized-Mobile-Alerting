# Research Methodology & Theoretical Formulations

## 1. Cognitive Retention Modeling (Ebbinghaus Forgetting Curve)

The retention probability $R(t)$ of a studied concept at time elapsed $t$ (days) is modeled following Ebbinghaus' exponential decay law modulated by the student's mastery stability factor $S$:

$$R(t) = \exp\left(-\frac{t}{S}\right)$$

where the memory stability index $S$ is dynamically adjusted based on the student's historical test performance $P \in [0, 1]$ and repetition count $n$:

$$S = S_0 \cdot (1 + \alpha \cdot P) \cdot \beta^n$$

with baseline stability $S_0 = 1.0$, performance sensitivity $\alpha = 0.5$, and repetition scaling $\beta = 1.25$.

---

## 2. Spaced Repetition Scheduling Protocol

Optimal review intervals $\Delta t_k$ for subsequent study sessions are computed by projecting the target retention threshold $R^* = 0.85$:

$$\Delta t_k = -S_k \cdot \ln(R^*)$$

Whenever $R(t) \le R^*$, the automated scheduling engine generates high-priority push notifications and injects targeted revision milestones into the student's study plan.

---

## 3. Bloom's Taxonomy Assessment Generation

The autonomous assessment engine partitions generated evaluation questions across the 6 cognitive tiers of Bloom's Revised Taxonomy:

| Level | Cognitive Objective | Prompt Template Strategy | Target Distribution |
| :--- | :--- | :--- | :---: |
| **L1: Remember** | Recall fundamental definitions and terms | Direct concept identification | 20% |
| **L2: Understand** | Explain ideas or mechanisms | Descriptive contrast & explanation | 25% |
| **L3: Apply** | Use information in concrete situations | Scenario-based problem solving | 25% |
| **L4: Analyze** | Distinguish between parts or relationships | Comparative breakdown & edge-cases | 15% |
| **L5: Evaluate** | Justify a stance or diagnostic decision | Error detection & optimization | 10% |
| **L6: Create** | Formulate new structures or syntheses | Integrative architectural formulation | 5% |
