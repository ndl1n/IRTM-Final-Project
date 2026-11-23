# E 評估與研究

負責：E（道路交通管理處罰條例）。改動：`src/evaluation/metrics.py`、`data/annotations/E.csv`、新增 `tests/test_evaluation.py` 與本文件。

## 怎麼重跑

在專案根目錄執行。結果寫到 `results/eval/<name>/`（`results/` 不進 Git，要保留的結果請另存）。

```bash
# 1. 用目前網站的搜尋系統，即時跑全部有標註的題目
python -X utf8 -m src.evaluation.metrics run --name baseline

# 只看某些角色或某種題目
python -X utf8 -m src.evaluation.metrics run --roles E --name baseline_E
python -X utf8 -m src.evaluation.metrics run --splits development,demo --name dev

# 2. 評估已存好的排名（manage.py export 的輸出、C 交來的檔案都可以）
python -X utf8 -m src.evaluation.metrics run --run results/local/baseline_run.json --roles A --name saved

# 3. 比較兩個版本（同一批題目、同一份標註）
python -X utf8 -m src.evaluation.metrics compare results/eval/before/run.json results/eval/after/run.json --name c_before_vs_after
```

每次 `run` 產生：`run.json`（排名，即時跑才有）、`summary.json`、`per_query.csv`、`report.md`。`compare` 產生 `compare.json`、`per_query_delta.csv`、`report.md`。

## 給 C 的交件格式

可直接用 C 的指令產生兩份排名，再用同一批消費題比較：

```powershell
python -X utf8 -m src.retrieval.compare_c
python -X utf8 -m src.evaluation.metrics compare results/local/C_baseline_run.json results/local/C_expanded_run.json --roles C --name c-mapping
```

這批題目與口語對照出自同一輪開發，結果用於檢查流程和分析案例。

下面三種任選一種，同一份語料（`corpus_id` 要一致），每題至少前 10 名：

1. `manage.py export` 的格式：`{"corpus_id", "index_id", "runs": [{"query_id", "results": [{"doc_id", "rank", "score"}]}]}`
2. `{"題號": ["doc_id", ...]}`，依名次排列
3. CSV，欄位 `query_id,doc_id,rank,score`

最方便的做法：改程式前跑一次 `run --name c_before`，改完重啟後再跑 `run --name c_after`，再用 `compare` 比較兩份 `run.json`。

## 判分規則

| 分數 | 意思 | E.csv 的判斷方式 |
|---|---|---|
| 2 直接相關 | 條文本身回答了問題（罰則、程序或要件） | 能指出哪一項、哪一款回答問題 |
| 1 背景 | 理解答案需要，但單靠它答不了 | 定義、適用範圍、相近情境 |
| 0 不相關 | 標了也不算分 | 只在需要特別排除時才標 |

- 每題至少一筆分數大於 0，否則程式直接報錯，不會靜默略過。
- **沒標註的文件一律算 0。** 報告附上「前 10 名有標註的比例」（judged@10）。目前約 13%，所以分數是保守的下限。
- 判分只看條文文字是否回答問題，不判斷個案在法律上會不會成立。理由寫在 `evidence`。
- MRR@10 和 Recall@5 把 1、2 分都當成相關；nDCG@10 用增益 2^分數−1，所以 2 分的權重是 1 分的 3 倍。
- 比較兩版用配對 sign-flip 檢定（16 題以內精確列舉）和 bootstrap 95% 信賴區間，固定亂數種子 13，重跑得到一樣的數字。

## 目前結果（開發題，不是正式評估）

語料 `official_rental_20261114_v3`，方法 `character_bigram_bm25_baseline`（k1=1.5、b=0.75），不限領域，取前 10 名。

| 題目來源 | 題數 | MRR@10 | Recall@5 | nDCG@10 |
|---|---|---|---|---|
| A 租賃 | 25 | 0.774 | 0.727 | 0.770 |
| E 交通 | 9 | 0.694 | 0.759 | 0.675 |
| 合計 | 34 | 0.753 | 0.735 | 0.745 |

比較示範：E 的 9 題限定「交通」領域後，nDCG@10 從 0.675 升到 0.835（3 題進步、0 題退步，p = 0.25）。題數太少，還不能說顯著。這組比較只用來示範 `compare`，不是改良成果。

## 報告可用的案例

**E_Q_05「收到罰單覺得不公平，可以去哪裡申訴或提告？」：nDCG@10 = 0。** 前 10 名沒有任何交通法條，第 1 名是勞基法第 74 條，第 2 名是消保法第 43 條，因為兩條都逐字出現「申訴」。交通條例的對應用語是第 9 條的「陳述意見」和第 87 條的「提起訴訟」，「罰單」在法條裡則寫成「違反道路交通管理事件通知單」。這就是專案動機說的生活用語和法律用語的落差，C 的口語對照可以拿這題當改良目標（E.csv 已有 `罰單 → 違反道路交通管理事件通知單`）。

**E_Q_01「騎機車闖紅燈被照相，會罰多少錢？」：第 1 名正確（第 53 條），但 Recall@5 只有 0.33。** 第 53 條寫的是「汽車駕駛人」，要靠第 3 條的「汽車（包括機車）」才知道機車也適用。這說明除了排名，系統還需要把定義條文推薦給使用者，正好是詞組探索可以補的地方。

## 使用者研究規格（交給 A 串接）

設計：受試者內 A/B，每人兩種介面都用。`variant=bm25` 只有搜尋框和結果；`variant=full` 加上詞組推薦和詞組探索。任務順序與介面順序用拉丁方格平衡，避免學習效應。每人 4 題，每題限時 5 分鐘。

| task_id | 任務（給受試者看的情境） | 正解 doc_id |
|---|---|---|
| T1 | 朋友收到罰單，但那天車是借給同事開的，他該怎麼辦？ | moj_K0040012_85 |
| T2 | 你對一張罰單不服，想知道有什麼程序可以表達意見 | moj_K0040012_9（或 87） |
| T3 | 開車經過斑馬線沒停讓行人，可能被罰多少 | moj_K0040012_44 |
| T4 | 國中生弟弟騎電動滑板車被攔下，誰會被處罰 | moj_K0040012_72-2、85-4 |

量測：任務完成率（交出的條文是否在正解內）、完成時間、查詢次數、是否用到推薦詞，以及每題後 1～5 分的信心和滿意度。

事件欄位：每筆都要有 `event`、`session_id`、`task_id`、`variant`、`corpus_id`、`index_id`、`ts`（ISO 時間）。不記姓名，也不記查詢全文。

| event | 額外欄位 |
|---|---|
| `task_start` | — |
| `search_submit` | `query_length`、`query_index`（這題的第幾次查詢）、`via`（`typed` 或 `suggestion`） |
| `results_shown` | `doc_ids`（前 5 名） |
| `doc_open` | `doc_id`、`rank` |
| `suggestion_click` | `phrase` |
| `phrase_explore` | `phrase`、`from_phrase` |
| `answer_submit` | `doc_id` |
| `task_end` | `completed`（true/false）、`confidence`、`satisfaction` |

## 限制與待辦

- 目前 34 題都是開發與展示題，標註者也是出題者，報告要標明。正式評估要等 LawFactsQA-TW 匯入並確認 ID 對應。
- judged@10 偏低。分數會低估系統，比較兩版時，影響取決於兩版各自排出多少未標註文件。正式評估前可以把兩版前 10 名的聯集拿去補標（pooling）。
- E.csv 的原文核對是 `snapshot_only`，尚未逐條比對官方網頁。
