**TKT-5 — Order history performance**
*Description:* `GET /orders?customer={id}` is slow for customers with many orders.
*Acceptance criteria:*
- An index exists on `orders.customer_id`.
- The endpoint returns the same results before and after the index is added.
- Results are paginated (`page`, `pageSize`); default page size is 20; pages beyond the last return an empty list with 200.
- Response time for a customer with 10 000 orders is under 500 ms.
