# AgentMesh Frontend v2.3A 鈥?Product Design System + Workspace Productization

鏈増鏈熀浜?v2.2B Historical Run Details 缁х画婕旇繘锛岀洰鏍囦笉鏄鍔?Runtime 鍔熻兘锛岃€屾槸鍏堥檷浣庘€淒emo / 鐜╁叿鎰熲€濓紝寤虹珛姝ｅ紡浜у搧鐨勮瑙変笌浜や簰鍩虹銆?
## 涓昏鍙樺寲

### 1. Design System
- 鏂板鏇村畬鏁寸殑 Surface / Typography / Border / Brand / Semantic / Radius / Shadow / Motion tokens銆?- 缁熶竴鎸夐挳銆佽〃鍗?Focus銆丒levation銆佸渾瑙掑拰鍔ㄦ晥璇█銆?- 淇濈暀鏃?CSS 鍙橀噺鍏煎宸叉湁 Agent / Extension / Task / Run Details 椤甸潰銆?
### 2. Workspace 棣栭〉浜у搧鍖?- 鏂板 `WorkspaceWelcome.tsx`銆?- 绌轰細璇濅笉鍐嶅彧鏈変竴鍙ユ杩庤锛屽鍔?4 涓换鍔″叆鍙ｏ細鍒嗘瀽鏁版嵁銆佹€荤粨鏂囨。銆佹绱㈢煡璇嗐€佹帓鏌ラ棶棰樸€?- 鐐瑰嚮寤鸿浼氱洿鎺ュ～鍏?Composer锛屼笉浼氳嚜鍔ㄦ彁浜ゃ€?- 涓诲尯鍔犲叆鏋佽交鐨勭綉鏍间笌鍝佺墝鍏夋檿锛屽鍔犲眰绾т絾涓嶈繃搴﹁楗般€?
### 3. Composer 浜у搧鍖?- 杩愯璁剧疆鍙繚鐣?Composer 涓€涓富鍏ュ彛锛岀Щ闄?Toolbar 閲嶅鐨勨€滆繍琛岃缃€濇寜閽€?- Composer 鍙樻垚娴姩浠诲姟杈撳叆闈㈡澘銆?- 澧炲姞 `Ctrl / Cmd + Enter` 蹇嵎鎵ц銆?- 鈥滆繍琛岃缃€濇枃妗堣皟鏁翠负鈥滄櫤鑳借繍琛屸€濓紝绐佸嚭榛樿鑷姩鍖栦綋楠屻€?
### 4. Session Rail
- 鈥?鈥濆皬鎸夐挳鍗囩骇涓烘槑纭殑鈥滄柊寤轰换鍔♀€濇寜閽€?- 浼氳瘽鍖烘敼鎴愨€滄渶杩戜細璇?/ 鏈€杩戔€濅俊鎭眰绾с€?- Active / Hover / 鐘舵€佺偣閲嶆柊璁捐銆?
### 5. Conversation Flow
- User Message / Agent Header / Run Details 鍏ュ彛閲嶆柊鍋氳瑙夊眰绾с€?- Historical Run Details銆丆itation銆丮arkdown銆丷AG Trace 绛夎兘鍔涗繚鎸佸師鏍枫€?- Citation 榛樿浠嶄负绱у噾鏉ユ簮鏉°€?
### 6. Runtime Settings
- `RUNTIME POLICY` 鏀逛负涓枃鈥滆繍琛岀瓥鐣モ€濄€?- Footer 璇存槑鏀规垚鏇寸鍚堜骇鍝佽涔夌殑鈥滄櫤鑳界瓥鐣モ€濄€?
## 鏂板鏂囦欢

- `src/features/workspace/WorkspaceWelcome.tsx`

## 涓昏淇敼鏂囦欢

- `src/components/common/Icon.tsx`
- `src/features/workspace/Workspace.tsx`
- `src/features/workspace/MessageHistory.tsx`
- `src/features/workspace/SessionRail.tsx`
- `src/features/workspace/RunSettingsDrawer.tsx`
- `src/styles/base.css`
- `src/styles/shell.css`
- `src/styles/workspace.css`
- `src/styles/citation.css`
- `src/styles/responsive.css`

## 鏈敼鍙?
- API Contract
- Citation / Provenance
- Historical Run reconstruction
- Run Details
- Agent / MCP / Tool 鏁版嵁閫昏緫
- 鐧诲綍鎺ュ彛
- Runtime / Go / Python
- npm dependencies

## 鏈湴楠岃瘉

瑕嗙洊鐪熷疄 `web-react/src` 鍚庯細

```powershell
cd "<agentmesh-root>\web-react"
npm run build
npm run dev
```

寤鸿楠岃瘉锛?
1. 绌轰細璇濆嚭鐜版柊鐨?Welcome + 4 涓换鍔″缓璁€?2. 鐐瑰嚮寤鸿鍚庡彧濉厖杈撳叆妗嗭紝涓嶈嚜鍔ㄦ彁浜ゃ€?3. Toolbar 涓嶅啀鍑虹幇閲嶅鐨勮繍琛岃缃叆鍙ｃ€?4. Composer 鐨勨€滄櫤鑳借繍琛屸€濆彲浠ユ甯告墦寮€杩愯绛栫暐 Drawer銆?5. Ctrl + Enter 鍙互杩愯浠诲姟銆?6. Markdown / Citation / Historical Run Details 浠嶆甯搞€?7. 鏅鸿兘浣?/ 鎵╁睍鑳藉姏 / 浠诲姟璁板綍椤甸潰鍙甯歌繘鍏ャ€?
## 闈欐€佹鏌?
- TypeScript / TSX parse diagnostics: 0
- Missing local relative imports: 0

