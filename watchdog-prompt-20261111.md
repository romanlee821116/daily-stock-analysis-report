# 守門員排程 prompt 修改稿（2026/11/11）— 待 Roman 核准後套用到 trig_01937Bw4m92c6C5iBV6Dn5cF

只改第 4、5 步，其餘（禁令、步驟 1~3、6）沿用現行版本。

## 新的第 4 步：依 suspension_reason 分兩條路，不可混用

2026/11/11 事故：守門員 08:06 看到兩個排程被 device_absent 暫停，就用 update_trigger 重新啟用。
結果「暫停狀態」被清掉——原本 Mac 醒來時系統會自動補跑被暫停的排程（11/06、11/10 都是 09:01 Mac 打開後自動補跑），
重新啟用後自動補跑消失、next_run_at 直接跳到明天，當天兩份報告都沒有。

4-A【suspension_reason = "device_absent"】Mac 睡著或 Claude 桌面 App 斷線
・不要 update_trigger、不要 fire_trigger，保留暫停狀態讓 Mac 一醒來就自動補跑。
・立刻 PushNotification 請 Roman 叫醒 Mac（掀開螢幕／動滑鼠，確認 Claude App 開著）。

4-B【enabled=false 且 suspension_reason 為空】被關掉：update_trigger 只傳 trigger_id + enabled=true，接著走 4-C。

4-C【enabled=true、suspension 為空、今天沒觸發】安靜沒觸發：
・對「盤前報告」fire_trigger（只傳 trigger_id，不帶 text），讀回確認 last_fired_at 是今天，最多兩次。
・no_signed_approval / cloud only 字樣原文照抄進通知。
・「ETF tracker」不自動補觸發，只通知。

4-D【全部正常】不發通知。

## 新的第 5 步：通知
・device_absent 時第一句：「Mac 睡著了，晨報還沒跑——叫醒 Mac 就會自動補跑」。
・補一句：「代表清晨保持清醒（tools/keepawake.sh）沒生效，請看 data/awake.log 最後幾行，或檢查螢幕是否蓋上、是否插電」。
・4-A 要明講「刻意沒有重新啟用，保留自動補跑」。
