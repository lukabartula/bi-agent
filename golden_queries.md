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

| # | Question | Pass/Fail | Notes |
|---|----------|-----------|-------|
| 1 | Total revenue | | |
| 2 | Revenue 2017 | | |
| 3 | Top categories | | |
| 4 | Revenue by state | | |
| 5 | Average order value | | |
| 6 | Avg delivery days | | |
| 7 | Late delivery rate | | |
| 8 | Worst review categories | | |
| 9 | Monthly trend 2018 | | |
| 10 | Ambiguous "best sellers" | | |
