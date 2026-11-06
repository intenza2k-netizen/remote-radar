# Gold label review checklist

The labels in `eval/gold.jsonl` are **drafts** written by a Claude model before any extractor ran. Please check them, most-contested jobs first. To fix a label, edit its `labels` object in `gold.jsonl` and set `"status": "reviewed"`, then run `uv run python eval/run_eval.py score` (free: no model calls).

How to read each entry: **Gold** is the draft label. **Notes** is the labeller's reasoning and doubts. The table shows only the fields where at least one model differs from gold. When *every* model agrees with each other and not with gold, the gold label is the likelier error.

## Likely label errors: all models agree against the gold label

| Job | Field | Gold | All models say |
|---|---|---|---|
| 2 Student Success Coach | role_category | other | support |
| 77 AI Trainer - Video Annotation | role_category | other | data |
| 661 Senior Site Reliability Engineer (SRE) | employment_type | unspecified | full_time |

## Jobs, most contested first

### 1. AI Trainer - Video Annotation - iMerit Technology
[open posting](https://remotive.com/remote-jobs/artificial-intelligence/ai-trainer-video-annotation-2091161) | job 77 | remotive | disagreement 9.7

- [ ] labels checked  (status: `draft`)
- **Gold:** role `other` | seniority `unspecified` | employment `contract` | salary `70000-80000 ?/year` | regions `worldwide`
- **Gold skills:** video-annotation
- **Notes:** AMBIGUOUS: data annotation / labelling work -> other (alternative: data). Salary line '70K-80K' has no currency symbol (currency left null, not guessed) and no period; magnitude implies annual. Plausibility for an independent-contractor annotator is doubtful, but labelled as written. Independent Contractor stated.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| role | `other` | `data` | `data` | `data` | `data` |
| salary | 70000-80000 ?/year | 70000-80000 USD/year | 70000-80000 USD/year | 70000-80000 UNSPECIFIED/year | 70000-80000 USD/year |
- **Skills most models added (gold lacks them):** data-annotation
- Per-job skills F1: claude-sonnet-5-5 0.50, gemma4:12b 0.33, qwen3.8:27b 0.50, gemma4:31b-it-q4_K_M 1.00

### 2. Channel Account Manager I, Service Providers - Huntress
[open posting](https://jobicy.com/jobs/159122-channel-account-manager-i-service-providers) | job 360 | jobicy | disagreement 9.1

- [ ] labels checked  (status: `draft`)
- **Gold:** role `sales` | seniority `junior` | employment `unspecified` | salary `54600 EUR/year` | regions `Ireland`
- **Gold skills:** salesforce, crm
- **Notes:** AMBIGUOUS salary: '54,600 base with on target earnings of 91,000 base plus equity'. Labelled the base only (single figure sets min and max); the OTE figure includes variable pay. Seniority: '2+ years' -> junior by the years rule (title 'I' is not a mapped level word).

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| seniority | `junior` | `junior` | `junior` | `junior` | `unspecified` |
| employment | `unspecified` | `unspecified` | `full_time` | `full_time` | `unspecified` |
| salary | 54600 EUR/year | 54600-91000 EUR/year | 54600-91000 EUR/year | 54600-91000 EUR/year | 54600-91000 EUR/year |
- **Skills most models added (gold lacks them):** account-management, channel-sales, cybersecurity, msp, partner-success
- Per-job skills F1: claude-sonnet-5-5 0.50, gemma4:12b 0.44, qwen3.8:27b 0.44, gemma4:31b-it-q4_K_M 0.50

### 3. Student Success Coach - FindTutors
[open posting](https://remoteOK.com/remote-jobs/remote-student-success-coach-findtutors-1136086) | job 2 | remoteok | disagreement 8.0

- [ ] labels checked  (status: `draft`)
- **Gold:** role `other` | seniority `unspecified` | employment `unspecified` | salary `20-40 GBP/hour` | regions `UK`
- **Gold skills:** -
- **Notes:** Role is student coaching/wellbeing (education), not customer support: 'other' chosen over 'support'. Self-set pay rate suggests self-employed but the text never says contract, so employment is unspecified. No concrete technologies named.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| role | `other` | `support` | `support` | `support` | `support` |
- **Skills most models added (gold lacks them):** coaching, goal-setting, student-wellbeing, study-skills
- Per-job skills F1: claude-sonnet-5-5 0.00, gemma4:12b 0.00, qwen3.8:27b 0.00, gemma4:31b-it-q4_K_M 0.00

### 4. Customer Experience Specialist - French Bilingual - Quince
[open posting](https://jobicy.com/jobs/154748-customer-experience-specialist-french-bilingual) | job 647 | jobicy | disagreement 7.7

- [ ] labels checked  (status: `draft`)
- **Gold:** role `support` | seniority `junior` | employment `unspecified` | salary `26 CAD/hour` | regions `Canada`
- **Gold skills:** customer-support
- **Notes:** Seniority: 'minimum 2 years of customer service' -> junior (0-2); the 'Senior Associate' career-track words are not the title. The up-to-1,300 CAD/month bonus is not salary. The five 9-6 days a week imply full-time but it is not stated. Candidates within 50 km of Toronto must be on-site, others remote -> Canada.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| seniority | `junior` | `unspecified` | `junior` | `junior` | `unspecified` |
| employment | `unspecified` | `unspecified` | `full_time` | `full_time` | `full_time` |
- **Skills most models added (gold lacks them):** phone-support, social-media-support
- Per-job skills F1: claude-sonnet-5-5 0.50, gemma4:12b 0.33, qwen3.8:27b 0.50, gemma4:31b-it-q4_K_M 0.00

### 5. Freelance Copywriter - Coalition Technologies
[open posting](https://remotive.com/remote-jobs/writing/freelance-copywriter-1749306) | job 98 | remotive | disagreement 6.4

- [ ] labels checked  (status: `draft`)
- **Gold:** role `marketing` | seniority `unspecified` | employment `contract` | salary `20000-35000 USD/year` | regions `worldwide`
- **Gold skills:** seo, copywriting
- **Notes:** AMBIGUOUS salary: the salary line says '$20k -$35k' (no period; annual by magnitude) but the body pays per word ($0.034-$0.07). Labelled the salary line since the prompt allows 'in the text or in the salary line'; a model that returns null (per-word pay is not a salary) is defensible. '2 to 4 years ... preferred' is not a requirement -> unspecified. Source tags (excel, quickbooks) belong to another posting and were ignored.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| seniority | `unspecified` | `unspecified` | `unspecified` | `junior` | `mid` |
| salary | 20000-35000 USD/year | 20000-35000 USD/year | 20000-35000 USD/? | 20000-35000 USD/? | 20000-35000 USD/? |
- **Skills most models added (gold lacks them):** content-writing, ecommerce, editing-proofreading, lead-generation
- Per-job skills F1: claude-sonnet-5-5 0.57, gemma4:12b 0.50, qwen3.8:27b 0.57, gemma4:31b-it-q4_K_M 1.00

### 6. Staff Quality Engineer - StackAdapt
[open posting](https://jobicy.com/jobs/152402-staff-quality-engineer) | job 205 | jobicy | disagreement 5.5

- [ ] labels checked  (status: `draft`)
- **Gold:** role `software_engineering` | seniority `principal` | employment `unspecified` | salary `136000-187000 USD/year` | regions `Canada, US`
- **Gold skills:** playwright, cypress, jest, junit, typescript, javascript, python, java, jenkins, github-actions, circleci, testrail, react, openai, claude, llm, test-automation
- **Notes:** AMBIGUOUS salary: the posting gives two bands, 'Canada ... $134,400-$184,800 CAD' and 'USA ... $136,000-$187,000 USD'. Labelled the USD band (matches the DB). A model returning the CAD band is equally defensible. 'Staff' in title -> principal. QA automation counts as software_engineering per the prompt.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| employment | `unspecified` | `unspecified` | `full_time` | `full_time` | `unspecified` |
| salary | 136000-187000 USD/year | none | 134400-184800 CAD/year | 134400-187000 UNSPECIFIED/year | 134400-187000 USD/year |

- **Skills most models missed (gold has them):** llm, test-automation
- **Skills most models added (gold lacks them):** ai-agents, api-testing, ci-cd, llm-evaluation, ui-testing
- Per-job skills F1: claude-sonnet-5-5 0.86, gemma4:12b 0.86, qwen3.8:27b 0.81, gemma4:31b-it-q4_K_M 0.94

### 7. Backend Engineer III - Monzo
[open posting](https://jobicy.com/jobs/152499-backend-engineer-iii) | job 207 | jobicy | disagreement 5.4

- [ ] labels checked  (status: `draft`)
- **Gold:** role `software_engineering` | seniority `unspecified` | employment `unspecified` | salary `85000-110000 GBP/year` | regions `UK`
- **Gold skills:** go, java, c, scala, cassandra, kafka, kubernetes, docker, envoy, aws, gcp, react, distributed-systems
- **Notes:** 'Engineer III' / 'L40' is a level but not one the prompt maps, and no years are given -> unspecified (a defensible alternative is mid or senior; another prompt gap). Technologies listed as 'what you'll be working on' (explicitly not required) are labelled, since the prompt says to include required and nice-to-have skills.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| seniority | `unspecified` | `unspecified` | `senior` | `senior` | `unspecified` |
| employment | `unspecified` | `unspecified` | `full_time` | `full_time` | `full_time` |

- **Skills most models missed (gold has them):** envoy
- **Skills most models added (gold lacks them):** envoy-proxy
- Per-job skills F1: claude-sonnet-5-5 0.92, gemma4:12b 0.89, qwen3.8:27b 0.88, gemma4:31b-it-q4_K_M 0.92

### 8. Forward Deployed Engineer (FDE) C-UAS - Defense Unicorns
[open posting](https://jobicy.com/jobs/159254-forward-deployed-engineer-fde-c-uas) | job 781 | jobicy | disagreement 5.2

- [ ] labels checked  (status: `draft`)
- **Gold:** role `data` | seniority `unspecified` | employment `unspecified` | salary `none` | regions `US`
- **Gold skills:** apache-iceberg, delta-lake, hudi, ceph, postgresql, pgvector, trino, duckdb, clickhouse, spark, kafka, airflow, dagster, argo-workflows, sql, kubernetes, linux, terraform, pulumi, gitops, change-data-capture, oauth, tak-server
- **Notes:** AMBIGUOUS role: forward-deployed engineer who deploys and operates a data platform and builds pipelines -> data (alternatives: devops_sre, software_engineering). Seniority: 'engineering leader' who mentors juniors but no level word or years visible (preferred-qualifications section truncated) -> unspecified. Skills taken from Required Qualifications; the list is long and the likeliest place for gold/model disagreement. US citizenship required.
- **Heads-up:** the DB holds a structured salary (148750-201250 USD/year) that was not part of the extractor input.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| role | `data` | `software_engineering` | `data` | `data` | `data` |
| seniority | `unspecified` | `unspecified` | `lead` | `lead` | `lead` |

- **Skills most models missed (gold has them):** ceph, change-data-capture, gitops, linux, oauth, pulumi, sql, terraform
- **Skills most models added (gold lacks them):** atak, loki, rook-ceph, strimzi, vector, velero, wintak, zarf
- Per-job skills F1: claude-sonnet-5-5 0.87, gemma4:12b 0.58, qwen3.8:27b 0.71, gemma4:31b-it-q4_K_M 0.63

### 9. Consultant Implementation Engineer - Harbor
[open posting](https://remoteOK.com/remote-jobs/remote-consultant-implementation-engineer-harbor-1136987) | job 21 | remoteok | disagreement 5.0

- [ ] labels checked  (status: `draft`)
- **Gold:** role `support` | seniority `unspecified` | employment `unspecified` | salary `none` | regions `US, Canada`
- **Gold skills:** -
- **Notes:** AMBIGUOUS role: customer-facing implementation/installation of the company's own software; prompt says 'solutions/implementation support' -> support (alternative: other). 'Intapp' is the product being implemented, not a stated skill, so not labelled. Seniority wording ('advanced expertise', 'expert') carries no level word or years.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| seniority | `unspecified` | `unspecified` | `senior` | `unspecified` | `unspecified` |
- **Skills most models added (gold lacks them):** accounting-systems, deployment-methodologies, enterprise-solutions, go, legal-systems
- Per-job skills F1: claude-sonnet-5-5 0.00, gemma4:12b 0.00, qwen3.8:27b 0.00, gemma4:31b-it-q4_K_M 0.00

### 10. Senior Site Reliability Engineer (SRE) - Makersite GmbH
[open posting](https://www.arbeitnow.com/jobs/companies/makersite-gmbh/remote-senior-site-reliability-engineer-sre-berlin-110950) | job 661 | arbeitnow | disagreement 4.9

- [ ] labels checked  (status: `draft`)
- **Gold:** role `devops_sre` | seniority `senior` | employment `unspecified` | salary `none` | regions `Germany`
- **Gold skills:** prometheus, grafana, cloudwatch, aws, ecs, azure, terraform, ansible, python
- **Notes:** AMBIGUOUS employment: 'a fixed, permanent position' states permanence, not hours; the prompt only allows full_time when stated, so unspecified (full_time is a defensible reading). Applicants must reside in Germany.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| employment | `unspecified` | `full_time` | `full_time` | `full_time` | `full_time` |
- **Skills most models added (gold lacks them):** backup-management, disaster-recovery, incident-management, iso-compliance, release-management, sre
- Per-job skills F1: claude-sonnet-5-5 0.75, gemma4:12b 0.64, qwen3.8:27b 0.67, gemma4:31b-it-q4_K_M 1.00

### 11. Remote Office Assistant - Coalition Technologies
[open posting](https://remotive.com/remote-jobs/marketing/remote-office-assistant-1680495) | job 49 | remotive | disagreement 4.7

- [ ] labels checked  (status: `draft`)
- **Gold:** role `other` | seniority `unspecified` | employment `full_time` | salary `35300-52000 USD/year` | regions `worldwide`
- **Gold skills:** google-sheets, excel, quickbooks, google-workspace, bookkeeping
- **Notes:** AMBIGUOUS salary: the salary line says '$35,3k- $52k' (garbled thousands separator, period unstated, clearly annual) while the body says '$15 to $25 per hour' for four US states only. Labelled the salary line as year (it is also what the DB parsed). Source tags (php, magento, photoshop...) are unrelated to the posting and were ignored. full_time inferred from the explicit '40 hours per week, Monday through Friday'.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| seniority | `unspecified` | `unspecified` | `junior` | `junior` | `unspecified` |
| salary | 35300-52000 USD/year | 15-25 USD/hour | 35300-52000 USD/year | 35300-52000 USD/year | 15-25 USD/hour |
- Per-job skills F1: claude-sonnet-5-5 1.00, gemma4:12b 0.37, qwen3.8:27b 0.89, gemma4:31b-it-q4_K_M 1.00

### 12. Tech Lead Full-Stack Rails Engineer - Mitre Media
[open posting](https://remotive.com/remote-jobs/software-development/tech-lead-full-stack-rails-engineer-2069746) | job 55 | remotive | disagreement 4.6

- [ ] labels checked  (status: `draft`)
- **Gold:** role `software_engineering` | seniority `lead` | employment `unspecified` | salary `170000-200000 USD/year` | regions `US, Canada`
- **Gold skills:** ruby, ruby-on-rails, postgresql, mysql, elasticsearch, redis, docker, stimulus, javascript, tailwind, html, llm, nlp, langchain, hugging-face, kubernetes, react, hotwire, graph-database, databricks
- **Notes:** AMBIGUOUS salary: salary line '$170k - $200k' vs body '$160,000-$200,000 CAD/USD'. Labelled the salary line. Region from 'USA, Canada' and +/-3h of Eastern Time. HTTP was listed as a skill in the posting but not labelled (too generic).

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| employment | `unspecified` | `unspecified` | `unspecified` | `full_time` | `unspecified` |
| salary | 170000-200000 USD/year | 170000-200000 USD/year | 160000-200000 USD/year | 160000-200000 USD/year | 160000-200000 USD/year |

- **Skills most models missed (gold has them):** databricks, graph-database, stimulus
- **Skills most models added (gold lacks them):** http, microservices, stimulusjs
- Per-job skills F1: claude-sonnet-5-5 0.83, gemma4:12b 0.82, qwen3.8:27b 0.87, gemma4:31b-it-q4_K_M 0.87

### 13. Data Analyst - Uni Systems
[open posting](https://www.arbeitnow.nl/jobs/companies/uni-systems/remote-data-analyst-petten-38896) | job 520 | arbeitnow | disagreement 4.5

- [ ] labels checked  (status: `draft`)
- **Gold:** role `data` | seniority `mid` | employment `unspecified` | salary `none` | regions `Netherlands`
- **Gold skills:** tableau, arcgis, data-visualization
- **Notes:** The posting contradicts itself (title 'Data Analyst', intro says 'AI & NLP Engineer'); the responsibilities are data analysis, so data. Seniority from 'minimum 5 years' (title silent) -> mid (3-5). Region from the Petten, Netherlands location plus the 'Remote' tag; the text never says where candidates must live.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| seniority | `mid` | `mid` | `senior` | `senior` | `senior` |
- **Skills most models added (gold lacks them):** data-analysis, data-cleaning, data-mapping, data-modeling, exploratory-data-analysis, supply-chain-analysis
- Per-job skills F1: claude-sonnet-5-5 0.55, gemma4:12b 0.50, qwen3.8:27b 0.67, gemma4:31b-it-q4_K_M 0.75

### 14. Technical Account Manager - Yuno
[open posting](https://remoteOK.com/remote-jobs/remote-technical-account-manager-yuno-1137540) | job 67 | remoteok | disagreement 4.1

- [ ] labels checked  (status: `draft`)
- **Gold:** role `support` | seniority `mid` | employment `full_time` | salary `none` | regions `Brazil`
- **Gold skills:** api-development, soap, json, xml, postman, soapui, openapi, html, css, javascript, go, python, nodejs, apache, nginx, mysql, oracle-database, postgresql, mongodb
- **Notes:** AMBIGUOUS role and seniority: technical account management = customer-facing technical support (alternative: management, since the body says it leads a team of TAMs; header says 'Individual Contributor'). No title level word; header says '+3 years', requirements say '5+ years' -> mid by the years rule (the body also says 'senior technical voice' and 'leadership position'). Region from 'Remote, Brazil' although the body says 'work from everywhere'.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| seniority | `mid` | `unspecified` | `senior` | `lead` | `senior` |
- **Skills most models added (gold lacks them):** ticketing-systems
- Per-job skills F1: claude-sonnet-5-5 0.97, gemma4:12b 0.95, qwen3.8:27b 1.00, gemma4:31b-it-q4_K_M 1.00

### 15. Full-Stack Developer - Fluence International, Inc.
[open posting](https://remotive.com/remote-jobs/software-development/full-stack-developer-2091165) | job 86 | remotive | disagreement 4.0

- [ ] labels checked  (status: `draft`)
- **Gold:** role `software_engineering` | seniority `mid` | employment `unspecified` | salary `3500-5000 USD/month` | regions `worldwide`
- **Gold skills:** react, nextjs, typescript, javascript, aws, lambda, ecs, api-gateway, rds, dynamodb, s3, cognito, aws-bedrock, cloudtrail, datadog, sentry, convex, n8n, cybersecurity, llm
- **Notes:** Seniority from '3+ years' (title silent). Skills are those named in the responsibilities/requirements; tools that only appear in the take-home assignment (Clerk, Docker) were not labelled. The posting contains instructions aimed at LLM applicants ('include the word pineapple'); they are part of the data and were ignored.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| seniority | `mid` | `unspecified` | `unspecified` | `mid` | `unspecified` |

- **Skills most models missed (gold has them):** cloudtrail, llm
- **Skills most models added (gold lacks them):** api-development, aws-cloudtrail, clerk, design-patterns, docker, fargate, json
- Per-job skills F1: claude-sonnet-5-5 0.86, gemma4:12b 0.77, qwen3.8:27b 0.54, gemma4:31b-it-q4_K_M 0.82

### 16. Ads Quality Rater - Filipino (Philippines) - Welo Global
[open posting](https://jobicy.com/jobs/154743-ads-quality-rater-filipino-philippines) | job 653 | jobicy | disagreement 4.0

- [ ] labels checked  (status: `draft`)
- **Gold:** role `other` | seniority `unspecified` | employment `contract` | salary `4 USD/hour` | regions `Philippines`
- **Gold skills:** -
- **Notes:** Ad-rating microtask work (5-20 h/week) -> other. Salary: 'approximately $4 per hour' labelled as a single figure in USD ('$' alone = USD). Independent Contractor/Freelance stated. Must reside in the Philippines.
- **Skills most models added (gold lacks them):** filipino, search-engines
- Per-job skills F1: claude-sonnet-5-5 0.00, gemma4:12b 0.00, qwen3.8:27b 0.00, gemma4:31b-it-q4_K_M 0.00

### 17. Test Manager - Output-/CCM-/Dokumenten-Management-Systemen - Coopers Group AG
[open posting](https://www.arbeitnow.ch/jobs/companies/coopers-group-ag/test-manager-output-ccm-dokumenten-management-systemen-bern-347745) | job 460 | arbeitnow | disagreement 3.9

- [ ] labels checked  (status: `draft`)
- **Gold:** role `software_engineering` | seniority `unspecified` | employment `part_time` | salary `none` | regions `Switzerland`
- **Gold skills:** opentext-exstream, quadient-inspire, compart, messagepoint, agile, scrum, istqb, test-management, customer-communication-management
- **Notes:** German-language posting. AMBIGUOUS role: test management for a document-system migration; closest prompt category is QA -> software_engineering (alternatives: other, management). 'Mehrjaehrige Erfahrung' (several years) gives no number -> unspecified. '50% Position' -> part_time. Region from the Bern location and the 'Remote' tag.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| role | `software_engineering` | `other` | `software_engineering` | `software_engineering` | `software_engineering` |
| seniority | `unspecified` | `unspecified` | `senior` | `lead` | `unspecified` |

- **Skills most models missed (gold has them):** customer-communication-management
- **Skills most models added (gold lacks them):** ccm, defect-management, output-management, performance-testing, test-data-management, uat
- Per-job skills F1: claude-sonnet-5-5 0.69, gemma4:12b 0.84, qwen3.8:27b 0.76, gemma4:31b-it-q4_K_M 0.78

### 18. Product Engineering Lead - Tether Operations Limited
[open posting](https://remoteOK.com/remote-jobs/remote-product-engineering-lead-tether-operations-limited-1137478) | job 46 | remoteok | disagreement 3.9

- [ ] labels checked  (status: `draft`)
- **Gold:** role `management` | seniority `lead` | employment `unspecified` | salary `none` | regions `-`
- **Gold skills:** javascript, react, llm-evals
- **Notes:** AMBIGUOUS role: '70% engineering leadership, 30% product', manages teams and team leads, but 'roll up your sleeves' -> management chosen (alternative: software_engineering). Region: only a company-wide 'team works remotely from every corner of the world'; no statement about candidate location, so left empty (a model answering worldwide is defensible). Preferred: on-device inference was not labelled as a skill.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| role | `management` | `management` | `software_engineering` | `management` | `software_engineering` |
- **Skills most models added (gold lacks them):** ai, api-development, mobile-development, on-device-inference
- Per-job skills F1: claude-sonnet-5-5 0.50, gemma4:12b 0.31, qwen3.8:27b 0.55, gemma4:31b-it-q4_K_M 0.75

### 19. Head of Strategic Partnerships, Tavily - Nebius
[open posting](https://jobicy.com/jobs/159089-head-of-strategic-partnerships-tavily) | job 315 | jobicy | disagreement 3.6

- [ ] labels checked  (status: `draft`)
- **Gold:** role `sales` | seniority `lead` | employment `unspecified` | salary `300000-377000 USD/year` | regions `US`
- **Gold skills:** business-development
- **Notes:** AMBIGUOUS role: 'Head of' (prompt: management) but the main work is identifying and closing partnerships, which the prompt lists under sales -> sales (decide by the main work). 'Head of' -> lead. The pay is an 'On Target Earnings Range', labelled as salary (period not stated, annual by magnitude); OTE includes variable pay, so a model returning null is defensible.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| employment | `unspecified` | `unspecified` | `full_time` | `unspecified` | `unspecified` |
- **Skills most models added (gold lacks them):** co-selling, negotiation, sales
- Per-job skills F1: claude-sonnet-5-5 0.33, gemma4:12b 0.20, qwen3.8:27b 0.40, gemma4:31b-it-q4_K_M 0.50

### 20. Director of Engineering, Cloud & Reliability - Boulevard
[open posting](https://jobicy.com/jobs/152496-director-of-engineering-cloud-reliability-2) | job 198 | jobicy | disagreement 3.5

- [ ] labels checked  (status: `draft`)
- **Gold:** role `management` | seniority `lead` | employment `unspecified` | salary `none` | regions `US`
- **Gold skills:** aws, kubernetes, terraform, gitops, datadog, ci-cd, infrastructure-as-code, rds, soc-2, hipaa, pci-dss
- **Notes:** AMBIGUOUS role: Director who leads a team of infra/reliability engineers -> management (alternative: devops_sre). AMBIGUOUS seniority: the prompt's title list has no 'director' (it maps 'head of' -> lead); labelled lead by analogy. This is a prompt gap, not a model error, if models disagree. The requirements section is truncated. DB holds a structured 209.5k-270k USD salary that the posting text does not state.
- **Heads-up:** the DB holds a structured salary (209500-270000 USD/year) that was not part of the extractor input.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| role | `management` | `management` | `devops_sre` | `management` | `management` |
| seniority | `lead` | `unspecified` | `lead` | `lead` | `lead` |
| employment | `unspecified` | `unspecified` | `full_time` | `unspecified` | `unspecified` |
- **Skills most models added (gold lacks them):** containerization, disaster-recovery, observability
- Per-job skills F1: claude-sonnet-5-5 0.80, gemma4:12b 0.81, qwen3.8:27b 0.91, gemma4:31b-it-q4_K_M 0.96

### 21. Principal Product Manager Strategic Initiatives - Thyme Care
[open posting](https://remoteOK.com/remote-jobs/remote-principal-product-manager-strategic-initiatives-thyme-care-1137510) | job 52 | remoteok | disagreement 3.5

- [ ] labels checked  (status: `draft`)
- **Gold:** role `product` | seniority `principal` | employment `unspecified` | salary `195500-230000 USD/year` | regions `-`
- **Gold skills:** product-management, llm
- **Notes:** 'Remote' with no region. Base salary stated in the body; bonus/equity ignored. Healthcare/oncology experience is domain experience, not labelled as a skill.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| employment | `unspecified` | `unspecified` | `full_time` | `unspecified` | `unspecified` |
- **Skills most models added (gold lacks them):** ai, data-integrations, data-modeling, workflow-tooling
- Per-job skills F1: claude-sonnet-5-5 0.44, gemma4:12b 0.33, qwen3.8:27b 0.36, gemma4:31b-it-q4_K_M 0.40

### 22. Sales Manager CH, KI-Software für Psychotherapeut:innen - VIA HealthTech
[open posting](https://www.arbeitnow.ch/jobs/companies/via-healthtech/sales-manager-ch-ki-software-fur-psychotherapeutinnen-zurich-223149) | job 185 | arbeitnow | disagreement 3.2

- [ ] labels checked  (status: `draft`)
- **Gold:** role `sales` | seniority `senior` | employment `unspecified` | salary `none` | regions `Switzerland`
- **Gold skills:** sales, crm, linkedin-sales-navigator, sales-automation
- **Notes:** German-language posting. Hands-on hunter selling role despite 'Manager' in the title -> sales, not management. Seniority: title silent, but the text says 'Die Rolle ist senior gedacht' (role is meant to be senior; mid-level accepted if exceptional) -> senior. Region: Zurich-based, 'auch remote', Swiss market -> Switzerland. Remaining part of the posting (benefits) was truncated.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| seniority | `senior` | `unspecified` | `senior` | `senior` | `senior` |
| employment | `unspecified` | `unspecified` | `unspecified` | `full_time` | `unspecified` |
- **Skills most models added (gold lacks them):** digital-health, inbound-sales, paid-advertising, webinars
- Per-job skills F1: claude-sonnet-5-5 0.67, gemma4:12b 0.57, qwen3.8:27b 0.67, gemma4:31b-it-q4_K_M 0.89

### 23. Graduate Transport Planner - Curtins
[open posting](https://remoteOK.com/remote-jobs/remote-graduate-transport-planner-curtins-1137542) | job 69 | remoteok | disagreement 3.2

- [ ] labels checked  (status: `draft`)
- **Gold:** role `other` | seniority `junior` | employment `unspecified` | salary `none` | regions `-`
- **Gold skills:** transport-planning
- **Notes:** Civil/transport engineering consultancy, no software or data work -> other. 'Graduate' -> junior by the title rule. No remote region is stated anywhere (company works in UK and Ireland), so empty. Only domain skill labelled: transport planning.
- **Skills most models added (gold lacks them):** civil-engineering, development-impact-studies, development-planning, junction-assessments, traffic-analysis, transport-assessments, travel-plans, urban-planning
- Per-job skills F1: claude-sonnet-5-5 0.29, gemma4:12b 0.17, qwen3.8:27b 0.17, gemma4:31b-it-q4_K_M 0.22

### 24. Partner Engineer - Contentstack
[open posting](https://jobicy.com/jobs/159156-partner-engineer-2) | job 425 | jobicy | disagreement 3.1

- [ ] labels checked  (status: `draft`)
- **Gold:** role `support` | seniority `unspecified` | employment `unspecified` | salary `none` | regions `EMEA`
- **Gold skills:** gdpr
- **Notes:** AMBIGUOUS role: partner technical enablement, explicitly 'unlike a traditional pre-sales Solutions Engineer' -> support (alternatives: sales, other). 'EMEA' is not in the prompt's region vocabulary; kept as written. The requirements section is truncated, so no years or tools are visible. DB holds a structured 80k-100k EUR salary that the posting text does not state.
- **Heads-up:** the DB holds a structured salary (80000-100000 EUR/year) that was not part of the extractor input.
- **Skills most models added (gold lacks them):** api-development, cms, composable-architecture, data-residency, system-design, technical-enablement
- Per-job skills F1: claude-sonnet-5-5 0.17, gemma4:12b 0.17, qwen3.8:27b 0.20, gemma4:31b-it-q4_K_M 0.40

### 25. Marketing Operations Specialist - Engine
[open posting](https://remoteOK.com/remote-jobs/remote-marketing-operations-specialist-engine-1136950) | job 20 | remoteok | disagreement 3.0

- [ ] labels checked  (status: `draft`)
- **Gold:** role `marketing` | seniority `senior` | employment `unspecified` | salary `none` | regions `US`
- **Gold skills:** -
- **Notes:** AMBIGUOUS seniority: title has no level word but the body says 'The Sr Marketing Operations Specialist'; labelled senior from the body. The source text itself is cut off mid-sentence, so no skills are visible. Region from the location line 'Remote - US'.
- **Skills most models added (gold lacks them):** campaign-execution, data-hygiene, revenue-operations
- Per-job skills F1: claude-sonnet-5-5 0.00, gemma4:12b 0.00, qwen3.8:27b 0.00, gemma4:31b-it-q4_K_M 1.00

### 26. Lead, SMB Onboarding, Thailand - Cloudbeds
[open posting](https://jobicy.com/jobs/159110-lead-smb-onboarding-thailand) | job 331 | jobicy | disagreement 3.0

- [ ] labels checked  (status: `draft`)
- **Gold:** role `management` | seniority `lead` | employment `unspecified` | salary `none` | regions `Thailand`
- **Gold skills:** -
- **Notes:** AMBIGUOUS role: people-management of an onboarding/customer-success team (coaching, performance management) -> management (alternative: support). Title 'Lead' -> lead. No concrete technologies in the visible text (requirements section truncated).

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| employment | `unspecified` | `unspecified` | `full_time` | `unspecified` | `unspecified` |
- **Skills most models added (gold lacks them):** customer-success, people-management
- Per-job skills F1: claude-sonnet-5-5 1.00, gemma4:12b 1.00, qwen3.8:27b 0.00, gemma4:31b-it-q4_K_M 0.00

### 27. (Senior) Product Designer - 1KOMMA5˚
[open posting](https://www.arbeitnow.com/jobs/companies/1komma50/senior-product-designer-berlin-336426) | job 907 | arbeitnow | disagreement 2.7

- [ ] labels checked  (status: `draft`)
- **Gold:** role `design` | seniority `senior` | employment `unspecified` | salary `none` | regions `Germany`
- **Gold skills:** product-design, ui-design, accessibility
- **Notes:** AMBIGUOUS seniority: title '(Senior) Product Designer' (optional level) with 'minimum 3 years' -> senior from the title word (mid is defensible). No design tools are named. 'chances of entering full-time' is odd wording, so employment is unspecified. 'You work remotely (Germany-wide)'.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| employment | `unspecified` | `unspecified` | `unspecified` | `unspecified` | `full_time` |
- **Skills most models added (gold lacks them):** agile, android, ios, ux-design, web-design
- Per-job skills F1: claude-sonnet-5-5 0.46, gemma4:12b 0.40, qwen3.8:27b 0.55, gemma4:31b-it-q4_K_M 0.86

### 28. Data Scientist - 100% Home Office - fino digital GmbH
[open posting](https://www.arbeitnow.com/jobs/companies/fino-digital-gmbh/data-scientist-all-genders-100-home-office-kassel-474872) | job 1008 | arbeitnow | disagreement 2.5

- [ ] labels checked  (status: `draft`)
- **Gold:** role `data` | seniority `unspecified` | employment `unspecified` | salary `none` | regions `Germany`
- **Gold skills:** python, sql, bigquery, machine-learning, llm, statistics
- **Notes:** German-language posting. 'einschlaegige Berufserfahrung' gives no number of years -> unspecified. 100% home office with quarterly office days in Kassel and fluent German required -> Germany.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| employment | `unspecified` | `unspecified` | `full_time` | `full_time` | `unspecified` |
- **Skills most models added (gold lacks them):** mlops, model-monitoring
- Per-job skills F1: claude-sonnet-5-5 0.86, gemma4:12b 0.80, qwen3.8:27b 0.86, gemma4:31b-it-q4_K_M 1.00

### 29. Account Executive, SMB - Emburse
[open posting](https://jobicy.com/jobs/159024-account-executive-smb-3) | job 266 | jobicy | disagreement 2.3

- [ ] labels checked  (status: `draft`)
- **Gold:** role `sales` | seniority `junior` | employment `unspecified` | salary `none` | regions `US`
- **Gold skills:** salesforce, zoom, generative-ai
- **Notes:** AMBIGUOUS seniority: '1-3+ years of B2B sales experience' straddles junior (0-2) and mid (3-5); labelled junior from the minimum of 1 year. The 'Compensation' heading is empty, so no salary.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| seniority | `junior` | `junior` | `junior` | `junior` | `unspecified` |
- **Skills most models added (gold lacks them):** accounting, invoicing-billing, negotiation, sales
- Per-job skills F1: claude-sonnet-5-5 0.55, gemma4:12b 0.60, qwen3.8:27b 0.67, gemma4:31b-it-q4_K_M 0.86

### 30. Developer Support Engineer - Algolia
[open posting](https://jobicy.com/jobs/159104-developer-support-engineer) | job 332 | jobicy | disagreement 2.2

- [ ] labels checked  (status: `draft`)
- **Gold:** role `support` | seniority `junior` | employment `unspecified` | salary `100000-125000 AUD/year` | regions `Australia`
- **Gold skills:** api-development, javascript, java, php, csharp, objective-c, swift, ruby, python, ios, android, github, shopify, magento
- **Notes:** Seniority: '{ 1 - 2 } years' (template placeholder left in the posting) -> junior by the years rule. 'Positions listed as Remote are only available within the specified country' -> Australia. Generic 'web development' and 'database management' not labelled as skills.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| seniority | `junior` | `unspecified` | `junior` | `junior` | `junior` |
| employment | `unspecified` | `unspecified` | `unspecified` | `full_time` | `unspecified` |
- **Skills most models added (gold lacks them):** rdbms, web-development
- Per-job skills F1: claude-sonnet-5-5 0.93, gemma4:12b 0.93, qwen3.8:27b 1.00, gemma4:31b-it-q4_K_M 0.97

### 31. Technical Product Lead AI Finance App - Bjak
[open posting](https://remoteOK.com/remote-jobs/remote-technical-product-lead-ai-finance-app-bjak-1137388) | job 33 | remoteok | disagreement 2.1

- [ ] labels checked  (status: `draft`)
- **Gold:** role `product` | seniority `lead` | employment `unspecified` | salary `none` | regions `worldwide`
- **Gold skills:** product-management, llm, distributed-systems, api-development
- **Notes:** Title 'Technical Product Lead' -> lead (title word rule) even though it is an individual-owner role. Skills are subjective here: kept only the clearly named ones (product management, LLMs, distributed systems, APIs); payments/KYC domain knowledge not labelled as skills. 'We hire globally' -> worldwide.
- **Skills most models added (gold lacks them):** ai, aml-kyc, banking, machine-learning, payments, rdbms, system-design, trading, transaction-monitoring
- Per-job skills F1: claude-sonnet-5-5 0.47, gemma4:12b 0.44, qwen3.8:27b 0.47, gemma4:31b-it-q4_K_M 0.50

### 32. Full Stack Engineer - Music - Spotify
[open posting](https://jobicy.com/jobs/159234-full-stack-engineer-music) | job 762 | jobicy | disagreement 2.1

- [ ] labels checked  (status: `draft`)
- **Gold:** role `software_engineering` | seniority `unspecified` | employment `unspecified` | salary `132948-189927 USD/year` | regions `US`
- **Gold skills:** java, react, typescript
- **Notes:** 'This range encompasses multiple levels' and no level word or years, so unspecified. Pay period is not stated but a US base salary range of this size is annual. Region: location USA plus 'within the ET time zone'.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| employment | `unspecified` | `unspecified` | `full_time` | `unspecified` | `unspecified` |
- **Skills most models added (gold lacks them):** api-development, backend, infrastructure
- Per-job skills F1: claude-sonnet-5-5 0.60, gemma4:12b 0.55, qwen3.8:27b 0.75, gemma4:31b-it-q4_K_M 1.00

### 33. Freelance Designer - Control Shift Video
[open posting](https://remoteOK.com/remote-jobs/remote-freelance-designer-control-shift-video-1136213) | job 11 | remoteok | disagreement 1.7

- [ ] labels checked  (status: `draft`)
- **Gold:** role `design` | seniority `unspecified` | employment `contract` | salary `none` | regions `US`
- **Gold skills:** adobe-creative-cloud, motion-graphics
- **Notes:** 'Pay based on freelancer's rate' is not a figure, so no salary. 'Project-based | Contract' header gives contract. Source tags are a generic RemoteOK tag dump and were ignored.
- **Skills most models added (gold lacks them):** branding, video-design, visual-storytelling
- Per-job skills F1: claude-sonnet-5-5 0.67, gemma4:12b 0.50, qwen3.8:27b 0.50, gemma4:31b-it-q4_K_M 0.67

### 34. Senior/Staff Product Engineer (Full Stack) - epilot GmbH
[open posting](https://www.arbeitnow.com/jobs/companies/epilot-gmbh/remote-senior-staff-product-engineer-full-stack-koln-16323) | job 654 | arbeitnow | disagreement 1.5

- [ ] labels checked  (status: `draft`)
- **Gold:** role `software_engineering` | seniority `senior` | employment `unspecified` | salary `none` | regions `-`
- **Gold skills:** typescript, react, svelte, aws, serverless, microfrontends, api-development, graphql, microservices, gcp, azure, scrum, kanban
- **Notes:** AMBIGUOUS seniority: title is 'Senior/Staff' (senior or principal); the body says 'Senior Product Engineer (Full Stack)', so senior. Region left empty: the posting says 'work remotely or from our office in Cologne' but never says candidates must live in Germany (Arbeitnow lists German jobs only).

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| seniority | `senior` | `senior` | `principal` | `senior` | `senior` |

- **Skills most models missed (gold has them):** microfrontends, serverless
- **Skills most models added (gold lacks them):** cybersecurity, xp
- Per-job skills F1: claude-sonnet-5-5 0.96, gemma4:12b 0.81, qwen3.8:27b 0.85, gemma4:31b-it-q4_K_M 0.88

### 35. Cloud Engineer Automation - Smile Digital Health
[open posting](https://remoteOK.com/remote-jobs/remote-cloud-engineer-automation-smile-digital-health-1137600) | job 85 | remoteok | disagreement 1.5

- [ ] labels checked  (status: `draft`)
- **Gold:** role `devops_sre` | seniority `senior` | employment `unspecified` | salary `120000-140000 USD/year` | regions `Canada`
- **Gold skills:** azure, terraform, helm, azure-devops, gitops, argocd, fluxcd, kubernetes, postgresql, azure-monitor, grafana, prometheus, opentelemetry, kafka, python, bash, ci-cd, claude, infrastructure-as-code
- **Notes:** AMBIGUOUS currency: '$120,000 - $140,000 a year' with a Toronto location is probably CAD, but the prompt rule is '$ alone means USD unless the text says otherwise' -> USD. Seniority from '6+ years' (title has no level word). Region only from the location line 'Toronto, Ontario'. Text was truncated after the salary line.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| salary | 120000-140000 USD/year | 120000-140000 USD/year | 120000-140000 USD/year | 120000-140000 CAD/year | 120000-140000 USD/year |

- **Skills most models missed (gold has them):** ci-cd, infrastructure-as-code
- **Skills most models added (gold lacks them):** azure-key-vault, azure-sql, finops, policy-as-code
- Per-job skills F1: claude-sonnet-5-5 0.88, gemma4:12b 0.90, qwen3.8:27b 0.89, gemma4:31b-it-q4_K_M 0.86

### 36. Senior Software Engineer LATAM - Wagmo
[open posting](https://remoteOK.com/remote-jobs/remote-senior-software-engineer-latam-wagmo-1137572) | job 81 | remoteok | disagreement 1.1

- [ ] labels checked  (status: `draft`)
- **Gold:** role `software_engineering` | seniority `senior` | employment `unspecified` | salary `none` | regions `LATAM`
- **Gold skills:** python, django, typescript, react, llm, openrouter, langsmith, github, linear, claude, coderabbit
- **Notes:** Skills = the 'Our Tech Stack' line (Python required, Django/TypeScript 'a plus'). The DB holds a structured 100k-140k USD salary that the posting text does not state, so salary is null here. '6 hours overlap with US Eastern' is a time-zone constraint; region comes from 'based in Latin America'.
- **Heads-up:** the DB holds a structured salary (100000-140000 USD/year) that was not part of the extractor input.

| field | gold | `claude-sonnet-5-5` | `gemma4:12b` | `qwen3.8:27b` | `gemma4:31b-it-q4_K_M` |
|---|---|---|---|---|---|
| employment | `unspecified` | `unspecified` | `full_time` | `unspecified` | `unspecified` |
- Per-job skills F1: claude-sonnet-5-5 0.96, gemma4:12b 0.92, qwen3.8:27b 1.00, gemma4:31b-it-q4_K_M 1.00

### 37. Tier III Service Desk Engineer - Unio Digital
[open posting](https://remotive.com/remote-jobs/information-technology/tier-iii-service-desk-engineer-2091045) | job 43 | remotive | disagreement 0.7

- [ ] labels checked  (status: `draft`)
- **Gold:** role `support` | seniority `senior` | employment `unspecified` | salary `none` | regions `worldwide`
- **Gold skills:** halopsa, hudu, intune, immybot, meraki, microsoft-365, avigilon, rhombus, active-directory, cisco
- **Notes:** Tier III help desk = technical support (alternative: devops_sre for IT systems admin). Title has no level word; '6+ years' -> senior. Skills taken from 'Our Technology Stack' and qualifications. Location line says 'Worldwide' although the company is Arizona-based.
- **Skills most models added (gold lacks them):** rmm
- Per-job skills F1: claude-sonnet-5-5 0.91, gemma4:12b 0.64, qwen3.8:27b 0.87, gemma4:31b-it-q4_K_M 0.91

### 38. Customer Support Specialist - Ultimate Marketing
[open posting](https://remoteOK.com/remote-jobs/remote-customer-support-specialist-ultimate-marketing-1137512) | job 53 | remoteok | disagreement 0.5

- [ ] labels checked  (status: `draft`)
- **Gold:** role `support` | seniority `unspecified` | employment `contract` | salary `none` | regions `worldwide`
- **Gold skills:** social-media, marketing, customer-support
- **Notes:** Performance-based bonus pay with no figure -> no salary (the DB holds a structured 50k-90k USD/year that the posting text does not state). Independent contractor (1099) stated. Looks like a low-quality / possibly scam-like posting; labelled as written.
- **Heads-up:** the DB holds a structured salary (50000-90000 USD/year) that was not part of the extractor input.

- **Skills most models missed (gold has them):** customer-support
- Per-job skills F1: claude-sonnet-5-5 1.00, gemma4:12b 0.67, qwen3.8:27b 1.00, gemma4:31b-it-q4_K_M 0.80

### 39. Senior Back-end Developer - Lemon.io
[open posting](https://remotive.com/remote-jobs/software-development/senior-back-end-developer-2091135) | job 83 | remotive | disagreement 0.3

- [ ] labels checked  (status: `draft`)
- **Gold:** role `software_engineering` | seniority `senior` | employment `full_time` | salary `none` | regions `EU, US, Canada, Australia, Singapore, Mexico, Saudi Arabia`
- **Gold skills:** go, python, kubernetes, distributed-systems, linux
- **Notes:** A recruiter-style ad covering several openings (SRE, DevOps, back-end Go/Python); title says Senior Back-end Developer so software_engineering. The 60-tag source tag list is generic and ignored. 'AI-assisted coding' not labelled as a skill. Regions from the location line; the body lists even more countries. 'Work full-time remotely' -> full_time.
- **Skills most models added (gold lacks them):** ai-assisted-coding
- Per-job skills F1: claude-sonnet-5-5 0.91, gemma4:12b 0.91, qwen3.8:27b 0.91, gemma4:31b-it-q4_K_M 1.00

### 40. Join our trusted contractor network - The Config Team
[open posting](https://www.arbeitnow.co.uk/jobs/companies/the-config-team/remote-join-our-trusted-contractor-network-skelmersdale-114060) | job 945 | arbeitnow | disagreement 0.0

- [ ] labels checked  (status: `draft`)
- **Gold:** role `other` | seniority `unspecified` | employment `contract` | salary `none` | regions `-`
- **Gold skills:** -
- **Notes:** Not a real vacancy: a speculative call to join a contractor network, with no role, skills or location. Included on purpose as a hard 'nothing to extract' case. Contractor stated. The 'United Kingdom' text is the job board's footer, not the employer's statement.
- Per-job skills F1: claude-sonnet-5-5 1.00, gemma4:12b 1.00, qwen3.8:27b 1.00, gemma4:31b-it-q4_K_M 1.00

