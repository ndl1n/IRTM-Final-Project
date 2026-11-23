"""B 的 PAT-tree：把語料每個位置開始的字串（後綴）建成壓縮樹，用來快速查詞組。"""


# ===== 樹的節點 =====
class _Node:
    __slots__ = ('doc', 'start', 'length', 'children', 'ends')

    def __init__(self, doc, start, length):
        # 邊上的文字：不複製，只記「第幾份文件、從哪開始、多長」
        self.doc = doc
        self.start = start
        self.length = length
        self.children = {}   # 往下分岔：下一個字 -> 子節點
        self.ends = []       # 在這裡結束的後綴起點 (文件編號, 位置)


class PATTreeIndex:
    backend = 'pat_tree'

    # ===== 建樹：把每份文件的每個位置都插進樹 =====
    def __init__(self, documents):
        self.doc_ids = [d['doc_id'] for d in documents]
        self.texts = [d['text'] for d in documents]
        self.root = _Node(0, 0, 0)
        self.node_count = 1
        for doc_index, text in enumerate(self.texts):
            for offset in range(len(text)):
                self._insert(doc_index, offset)

    # ===== 插入一個後綴 texts[d][i:] =====
    def _insert(self, d, i):
        text = self.texts[d]
        n = len(text)
        node = self.root
        pos = i                                   # 目前比對到後綴的哪個字
        while True:
            # 情況 1：後綴用完了 → 記在這個節點
            if pos == n:
                node.ends.append((d, i))
                return

            # 情況 2：沒有這個字的分岔 → 新開一片葉子
            child = node.children.get(text[pos])
            if child is None:
                leaf = _Node(d, pos, n - pos)
                leaf.ends.append((d, i))
                node.children[text[pos]] = leaf
                self.node_count += 1
                return

            # 情況 3：整條邊都相同 → 直接走到下一個節點
            label = self.texts[child.doc]
            ls, ll = child.start, child.length
            remaining = n - pos
            if remaining >= ll and text[pos:pos + ll] == label[ls:ls + ll]:
                pos += ll
                node = child
                continue

            # 情況 4：走到邊中間就不同 → 找出不同的位置，把邊切成兩段
            k = 1                                 # 第一個字已確定相同
            limit = min(ll, remaining)
            while k < limit and text[pos + k] == label[ls + k]:
                k += 1
            mid = _Node(child.doc, ls, k)         # 新的分岔點
            node.children[text[pos]] = mid
            child.start += k                      # 原本的邊剩下後半段
            child.length -= k
            mid.children[label[child.start]] = child
            self.node_count += 1
            pos += k
            node = mid                            # 下一輪在分岔點掛上新後綴

    # ===== 查詢第 1 步：沿著詞組往下走，找到它在樹上的位置 =====
    def _locate(self, phrase):
        node = self.root
        pos, m = 0, len(phrase)
        while pos < m:
            child = node.children.get(phrase[pos])
            if child is None:                     # 沒路可走 → 查無結果
                return None
            label = self.texts[child.doc]
            take = min(child.length, m - pos)
            if phrase[pos:pos + take] != label[child.start:child.start + take]:
                return None                       # 邊上的字對不上 → 查無結果
            pos += take
            node = child
        return node

    # ===== 查詢第 2 步：收集該節點底下的所有出現位置 =====
    def _collect(self, node):
        out = []
        stack = [node]
        while stack:
            current = stack.pop()
            out.extend(current.ends)
            stack.extend(current.children.values())
        return out

    # ===== 對外查詢：回傳格式與掃描版相同 =====
    def lookup(self, phrase):
        if not phrase:
            raise ValueError('phrase cannot be blank')
        node = self._locate(phrase)
        hits = self._collect(node) if node is not None else []

        # 依文件分組，文件和位置都由小到大排序
        by_doc = {}
        for d, offset in hits:
            by_doc.setdefault(d, []).append(offset)
        length = len(phrase)
        matches = []
        for d in sorted(by_doc):
            offsets = sorted(by_doc[d])
            matches.append({'doc_id': self.doc_ids[d], 'tf': len(offsets),
                            'positions': [{'start': s, 'end': s + length} for s in offsets]})
        return {'phrase': phrase, 'frequency': sum(m['tf'] for m in matches),
                'df': len(matches), 'documents': matches, 'backend': self.backend}

    # ===== 詞組擷取用：先算好每個節點底下有幾個出現位置（只算一次）=====
    def _subtree_counts(self):
        if getattr(self, '_counts', None) is None:
            counts, order, stack = {}, [], [self.root]
            while stack:
                node = stack.pop()
                order.append(node)
                stack.extend(node.children.values())
            for node in reversed(order):          # 從下往上加總
                counts[id(node)] = len(node.ends) + sum(counts[id(c)] for c in node.children.values())
            self._counts = counts
        return self._counts

    # ===== 只回傳詞組出現次數，不列位置 =====
    def count(self, phrase):
        node = self._locate(phrase) if phrase else None
        return self._subtree_counts()[id(node)] if node is not None else 0

    # ===== 列出所有重複出現的字串（每個分岔點就是一個）=====
    # 回傳：(字串, 出現次數, 後面接的字與次數, 所有出現位置)
    def repeated_strings(self, min_freq=2, min_len=2, max_len=10):
        counts = self._subtree_counts()
        stack = [(child, '') for child in self.root.children.values()]
        while stack:
            node, prefix = stack.pop()
            freq = counts[id(node)]
            if freq < min_freq:                   # 次數太少，底下更少 → 整枝跳過
                continue
            phrase = prefix + self.texts[node.doc][node.start:node.start + node.length]
            if len(phrase) > max_len:             # 太長 → 跳過
                continue
            if len(phrase) >= min_len:
                right = {ch: counts[id(c)] for ch, c in node.children.items()}
                if node.ends:
                    right[None] = len(node.ends)  # None 代表文件結尾
                yield phrase, freq, right, self._collect(node)
            stack.extend((c, phrase) for c in node.children.values())

    # ===== 樹的大小統計 =====
    def stats(self):
        return {'documents': len(self.texts), 'suffixes': sum(len(t) for t in self.texts),
                'nodes': self.node_count}
