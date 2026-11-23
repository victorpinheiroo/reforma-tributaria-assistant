# reforma-tributaria-assistant

Brazil is replacing five consumption taxes with a dual VAT (CBS + IBS) between 2026 and 2033, one
of the largest VAT transitions in the world. This assistant answers questions with the exact legal
article and computes amounts by calling the Federal Revenue's official open-source tax engine,
never by letting the model do the math.

> Status: milestone 1 done. The official calculator (1.7.2) runs locally and 6 calculations match
> expectations; 6 of 8 free Databricks-hosted models do native tool calling 8/8. See
> [docs/PLAN.md](docs/PLAN.md).
>
> Not tax advice: answers come from official documents and tools and do not replace an accountant.
