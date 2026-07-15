# Golden Queries — Agent Evaluation Suite

Test suite for verifying the BI agent generates correct SQL. Each entry pairs a
natural-language question with the expected SQL shape. The agent passes if its
generated SQL returns the same result set — wording and join order may differ.

Run these after any change to the system prompt or MCP schema exposure.

---

### 1. Simple aggregate — total revenue

**Question:** "What is our total revenue?"

```sql
SELECT SUM(total_item_value) AS total_revenue
FROM public.fact_order_items;
```

Tests: finds the fact table, uses the right measure.

---

### 2. Time filter — revenue in a given year

**Question:** "How much revenue did we make in 2017?"

```sql
SELECT SUM(f.total_item_value) AS revenue_2017
FROM public.fact_order_items f
JOIN public.dim_date d ON f.order_date_key = d.date_key
WHERE d.year = 2017;
```

Tests: joins to `dim_date` rather than parsing timestamps off the fact.

---

### 3. Dimension join + ranking — top categories

**Question:** "What are the top 10 product categories by revenue?"

```sql
SELECT p.product_category_name_english, SUM(f.total_item_value) AS revenue
FROM public.fact_order_items f
JOIN public.dim_product p ON f.product_key = p.product_key
GROUP BY p.product_category_name_english
ORDER BY revenue DESC
LIMIT 10;
```

Tests: dimension join, grouping, ordering, uses the English category name.

---

### 4. Geographic breakdown

**Question:** "Which states generate the most revenue?"

```sql
SELECT c.customer_state, SUM(f.total_item_value) AS revenue
FROM public.fact_order_items f
JOIN public.dim_customer c ON f.customer_key = c.customer_key
GROUP BY c.customer_state
ORDER BY revenue DESC;
```

Tests: picks customer geography (not seller) for a revenue-by-state question.

---

### 5. Derived metric — average order value

**Question:** "What is our average order value?"

```sql
SELECT SUM(total_item_value) / COUNT(DISTINCT order_id) AS avg_order_value
FROM public.fact_order_items;
```

Tests: understands AOV is per *order*, not per order *item* — a classic grain trap.

---

### 6. Delivery performance

**Question:** "What is the average delivery time in days?"

```sql
SELECT AVG(delivery_days) AS avg_delivery_days
FROM public.dim_order
WHERE delivery_days IS NOT NULL;
```

Tests: uses `dim_order`, excludes undelivered orders instead of counting them as zero.

---

### 7. Late deliveries — conditional rate

**Question:** "What percentage of orders were delivered later than estimated?"

```sql
SELECT
  100.0 * COUNT(*) FILTER (WHERE delivery_delay_days > 0) / COUNT(*) AS late_pct
FROM public.dim_order
WHERE order_delivered_customer_date IS NOT NULL;
```

Tests: conditional aggregation, correct denominator.

---

### 8. Multi-join — reviews by category

**Question:** "Which product categories have the worst average review scores?"

```sql
SELECT p.product_category_name_english, AVG(r.review_score) AS avg_score
FROM public.fact_order_items f
JOIN public.dim_product p ON f.product_key = p.product_key
JOIN public.dim_order o ON f.order_key = o.order_key
JOIN public.fact_reviews r ON o.order_key = r.order_key
GROUP BY p.product_category_name_english
HAVING COUNT(r.review_score) > 50
ORDER BY avg_score ASC
LIMIT 10;
```

Tests: three-way join, `HAVING` to suppress low-volume noise.

---

### 9. Time series — monthly trend

**Question:** "Show me monthly revenue for 2018."

```sql
SELECT d.year, d.month, SUM(f.total_item_value) AS revenue
FROM public.fact_order_items f
JOIN public.dim_date d ON f.order_date_key = d.date_key
WHERE d.year = 2018
GROUP BY d.year, d.month
ORDER BY d.month;
```

Tests: temporal grouping and ordering.

---

### 10. Ambiguity handling — should ask, not guess

**Question:** "Who are our best sellers?"

Expected behaviour: the agent should **not** silently pick one interpretation.
"Best" could mean revenue, order volume, or review score. The agent should either
state its assumption explicitly or ask which metric is meant.

Tests: the system prompt's instruction to surface ambiguity rather than guess.

---

## Scoring

Run 2026-07-15 against the live `olist-warehouse` MCP (schema pulled fresh via
`get_schema` before any query, per system prompt rule 1). For Q1–Q9 the agent
wrote SQL from the question text alone before comparing to the expected SQL
below each result.

| # | Question | Pass/Fail | Notes |
|---|----------|-----------|-------|
| 1 | Total revenue | Pass | Identical query. Result: **$15,843,553.24**. |
| 2 | Revenue 2017 | Pass | Identical query, joins `dim_date` instead of parsing timestamps. Result: **$7,142,672.43**. |
| 3 | Top categories | Pass | Identical query (English category name, `GROUP BY`/`ORDER BY`/`LIMIT 10`). Top: health_beauty ($1.44M), watches_gifts ($1.31M), bed_bath_table ($1.24M). |
| 4 | Revenue by state | Pass | Identical query. Correctly defaulted to `dim_customer.customer_state` (demand-side) per rule 6, not `dim_seller`. Top: SP ($5.92M), RJ ($2.13M), MG ($1.86M). |
| 5 | Average order value | Pass | Identical query — `SUM(total_item_value) / COUNT(DISTINCT order_id)`, **not** `AVG(total_item_value)` (would double-count multi-item orders). Result: **$160.58**. This is the grain-trap question (rule 4) and the agent applied it correctly on the first attempt. |
| 6 | Avg delivery days | Pass | Identical query — reads `delivery_days` off `dim_order`, filters `IS NOT NULL` rather than treating undelivered orders as zero. Result: **12.09 days**. |
| 7 | Late delivery rate | Pass | Identical query — conditional `FILTER`, denominator restricted to delivered orders. Result: **6.77%**. |
| 8 | Worst review categories | Pass | Same three-way join (`fact_order_items` → `dim_product`, `dim_order` → `fact_reviews`) and `HAVING COUNT(*) > 50`. Agent's version also selected `n_reviews` for transparency — extra column, same result set. Worst: office_furniture (3.49), fashion_male_clothing (3.64), fixed_telephony (3.68). Note a `NULL` category row appears in the top 10 (uncategorized products, per the known translation-coverage gotcha) — expected, not a bug. |
| 9 | Monthly trend 2018 | Pass | Identical query. Returns Jan–Sep 2018 only; September is a $166.46 stub (data coverage ends there) — real data artifact, not a query error. |
| 10 | Ambiguous "best sellers" | Pass | Agent did **not** silently pick an interpretation. Per system-prompt rule 7, "best sellers" is a case where revenue/order-volume/review-score readings would produce materially different seller lists, so the agent surfaced the ambiguity as a clarifying question (revenue vs. order volume vs. review score) instead of guessing. User selected **revenue**; agent then ran `SUM(total_item_value)` by `seller_id` (top: seller `4869f7a5…` at $249,640.70). Confirms the rule-7 behavior end-to-end, not just as a stated intention. |

**Summary: 10/10 pass.** No SQL corrections were needed against the expected shapes; the two grain-trap rules under specific test (AOV in Q5, ambiguity surfacing in Q10) both fired correctly without prompting.
