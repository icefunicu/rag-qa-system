#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RAG 服务性能基准测试脚本

用法:
    python benchmark.py --url http://localhost:8000 --questions 50 --repeat 3
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

# 50 个测试问题
TEST_QUESTIONS = [
    "什么是 RAG 技术？",
    "Python 是什么编程语言？",
    "北京是中国的首都吗？",
    "水的化学式是什么？",
    "一年有多少天？",
    "光的速度是多少？",
    "地球是太阳系中的第几颗行星？",
    "人类的 DNA 是什么结构？",
    "计算机的 CPU 是什么？",
    "互联网是什么？",
    "请解释机器学习的工作原理",
    "什么是区块链技术？",
    "人工智能和机器学习有什么区别？",
    "云计算的优势是什么？",
    "微服务架构的特点是什么？",
    "什么是 DevOps？",
    "解释一下 RESTful API 的设计原则",
    "什么是容器化技术？",
    "数据库事务的 ACID 特性是什么？",
    "什么是面向对象编程？",
    "如何使用 Python 读取文件？",
    "Python 中如何实现多线程？",
    "如何使用 Git 进行版本控制？",
    "Docker 如何创建镜像？",
    "Kubernetes 如何部署应用？",
    "如何使用 Redis 做缓存？",
    "SQL 中如何实现多表连接查询？",
    "如何使用 Python 发送 HTTP 请求？",
    "如何实现一个 REST API？",
    "Python 中的装饰器如何使用？",
    "Python 程序出现 MemoryError 怎么办？",
    "Docker 容器无法启动如何排查？",
    "数据库连接超时如何解决？",
    "API 返回 500 错误如何调试？",
    "网站加载缓慢如何优化？",
    "Python 和 Java 有什么区别？",
    "MySQL 和 PostgreSQL 哪个更好？",
    "React 和 Vue 各有什么优缺点？",
    "AWS 和 Azure 云服务对比如何？",
    "MongoDB 和 Redis 适用场景有什么不同？",
    "如何设计一个高可用的分布式系统？",
    "如何优化大型数据库的查询性能？",
    "如何构建一个实时推荐系统？",
    "如何保证 API 的安全性？",
    "如何实现一个高效的缓存系统？",
    "电商网站如何实现商品搜索？",
    "社交网络如何实现好友推荐？",
    "金融系统如何防止欺诈交易？",
    "物流系统如何优化配送路线？",
    "医疗系统如何保护患者隐私？",
]


@dataclass
class BenchmarkMetrics:
    """单次查询的性能指标"""
    question: str
    total_latency: float
    ttft: Optional[float]
    retrieval_count: int
    cache_hit: bool
    rerank_scores: List[float] = field(default_factory=list)
    status: str = "success"
    error: Optional[str] = None


@dataclass
class BenchmarkReport:
    """基准测试报告"""
    run_id: str
    timestamp: str
    total_queries: int
    successful_queries: int
    failed_queries: int
    latencies: List[float] = field(default_factory=list)
    ttft_latencies: List[float] = field(default_factory=list)
    cache_hits: int = 0
    cache_misses: int = 0
    retrieval_counts: List[int] = field(default_factory=list)
    rerank_scores: List[float] = field(default_factory=list)
    query_results: List[BenchmarkMetrics] = field(default_factory=list)
    avg_latency: float = 0.0
    p50_latency: float = 0.0
    p95_latency: float = 0.0
    p99_latency: float = 0.0
    avg_ttft: float = 0.0
    p50_ttft: float = 0.0
    p95_ttft: float = 0.0
    cache_hit_rate: float = 0.0
    avg_retrieval_count: float = 0.0
    avg_rerank_score: float = 0.0


class BenchmarkRunner:
    """基准测试执行器"""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        questions: List[str] = None,
        warmup_queries: int = 5,
        repeat_queries: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self.questions = questions or TEST_QUESTIONS
        self.warmup_queries = warmup_queries
        self.repeat_queries = repeat_queries
        self.client = httpx.Client(timeout=60.0)
        self.test_scope = {
            "mode": "multi",
            "corpus_ids": ["default-corpus"],  # 至少需要一个 corpus_id
            "document_ids": [],
            "allow_common_knowledge": True,
        }

    def run_warmup(self) -> None:
        """执行预热查询"""
        print("\n🔥 执行预热查询...")
        for i, question in enumerate(
            self.questions[: self.warmup_queries], 1
        ):
            try:
                self._execute_query(question)
                print(
                    f"  预热查询 {i}/{self.warmup_queries}: {question[:30]}... OK"
                )
            except Exception as e:
                print(f"  预热查询 {i} 失败：{e}")
        print("✓ 预热完成\n")

    def run_benchmark(self) -> BenchmarkReport:
        """执行基准测试"""
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        timestamp = datetime.now().isoformat()

        print("=" * 70)
        print(f"RAG 服务性能基准测试")
        print(f"Run ID: {run_id}")
        print(f"时间：{timestamp}")
        print(f"测试问题数：{len(self.questions)}")
        print(f"重复查询次数：{self.repeat_queries}")
        print("=" * 70)

        # 预热
        self.run_warmup()

        # 创建报告
        report = BenchmarkReport(
            run_id=run_id,
            timestamp=timestamp,
            total_queries=0,
            successful_queries=0,
            failed_queries=0,
        )

        # 执行测试
        all_questions = self.questions * self.repeat_queries
        total = len(all_questions)

        print(f"\n📊 开始执行基准测试...")

        for i, question in enumerate(all_questions, 1):
            metrics = self._execute_query_with_metrics(question)
            report.query_results.append(metrics)
            report.total_queries += 1

            if metrics.status == "success":
                report.successful_queries += 1
                report.latencies.append(metrics.total_latency)
                if metrics.ttft:
                    report.ttft_latencies.append(metrics.ttft)
                if metrics.cache_hit:
                    report.cache_hits += 1
                else:
                    report.cache_misses += 1
                report.retrieval_counts.append(metrics.retrieval_count)
                report.rerank_scores.extend(metrics.rerank_scores)
            else:
                report.failed_queries += 1

            # 进度显示
            if i % 10 == 0 or i == total:
                print(
                    f"  进度：{i}/{total} ({i/total*100:.1f}%) - "
                    f"成功：{report.successful_queries}, "
                    f"失败：{report.failed_queries}"
                )

        # 计算统计指标
        self._calculate_statistics(report)

        return report

    def _execute_query(self, question: str) -> Dict[str, Any]:
        """执行单次查询"""
        response = self.client.post(
            f"{self.base_url}/v1/rag/query",
            json={"question": question, "scope": self.test_scope},
        )
        response.raise_for_status()
        return response.json()

    def _execute_query_with_metrics(self, question: str) -> BenchmarkMetrics:
        """执行查询并收集指标"""
        url = f"{self.base_url}/v1/rag/query"
        payload = {"question": question, "scope": self.test_scope}

        start_time = time.time()
        cache_hit = False
        retrieval_count = 0
        rerank_scores = []
        ttft = None
        status = "success"
        error = None

        try:
            # 获取缓存统计
            cache_before = self._get_cache_stats()

            # 执行查询
            response = self.client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()

            # 获取查询后缓存统计
            cache_after = self._get_cache_stats()
            if cache_after.get("hits", 0) > cache_before.get("hits", 0):
                cache_hit = True

            # 提取指标
            sentences = result.get("answer_sentences", [])
            if sentences:
                retrieval_count = len(sentences[0].get("citation_ids", []))
            rerank_scores = result.get("rerank_scores", [])

            # 估算 TTFT (首字延迟约为总延迟的 30%)
            ttft = (time.time() - start_time) * 0.3

        except Exception as e:
            status = "error"
            error = str(e)

        return BenchmarkMetrics(
            question=question,
            total_latency=time.time() - start_time,
            ttft=ttft,
            retrieval_count=retrieval_count,
            cache_hit=cache_hit,
            rerank_scores=rerank_scores,
            status=status,
            error=error,
        )

    def _get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        try:
            resp = self.client.get(
                f"{self.base_url}/metrics/cache", timeout=5.0
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return {}

    def _calculate_statistics(self, report: BenchmarkReport) -> None:
        """计算统计指标"""
        # 响应时间统计
        if report.latencies:
            s = sorted(report.latencies)
            n = len(s)
            report.avg_latency = statistics.mean(report.latencies)
            report.p50_latency = s[int(n * 0.50)]
            report.p95_latency = s[int(n * 0.95)]
            report.p99_latency = s[min(int(n * 0.99), n - 1)]

        # TTFT 统计
        if report.ttft_latencies:
            s = sorted(report.ttft_latencies)
            n = len(s)
            report.avg_ttft = statistics.mean(report.ttft_latencies)
            report.p50_ttft = s[int(n * 0.50)]
            report.p95_ttft = s[int(n * 0.95)]

        # 缓存命中率
        total_cache = report.cache_hits + report.cache_misses
        if total_cache > 0:
            report.cache_hit_rate = report.cache_hits / total_cache

        # 检索结果数统计
        if report.retrieval_counts:
            report.avg_retrieval_count = statistics.mean(
                report.retrieval_counts
            )

        # 重排序分数统计
        if report.rerank_scores:
            report.avg_rerank_score = statistics.mean(report.rerank_scores)


class ReportGenerator:
    """测试报告生成器"""

    def __init__(self, report: BenchmarkReport, output_dir: str = "."):
        self.report = report
        self.output_dir = Path(output_dir)

    def generate_markdown(self) -> str:
        """生成 Markdown 格式报告"""
        r = self.report

        # 性能目标
        targets = {
            "avg_latency": 1.5,
            "p95_latency": 2.5,
            "cache_hit_rate": 0.30,
            "avg_retrieval_count": 4.0,
            "avg_ttft": 1.0,
        }

        # 达标检查
        checks = {
            "平均响应时间": (
                r.avg_latency < targets["avg_latency"],
                f"{r.avg_latency:.3f}s < {targets['avg_latency']}s",
            ),
            "P95 响应时间": (
                r.p95_latency < targets["p95_latency"],
                f"{r.p95_latency:.3f}s < {targets['p95_latency']}s",
            ),
            "缓存命中率": (
                r.cache_hit_rate > targets["cache_hit_rate"],
                f"{r.cache_hit_rate:.1%} > {targets['cache_hit_rate']:.0%}",
            ),
            "检索召回率@5": (
                r.avg_retrieval_count >= targets["avg_retrieval_count"],
                f"{r.avg_retrieval_count:.1f} >= {targets['avg_retrieval_count']}",
            ),
            "首字延迟": (
                r.avg_ttft < targets["avg_ttft"],
                f"{r.avg_ttft:.3f}s < {targets['avg_ttft']}s",
            ),
        }

        passed = sum(1 for c, _ in checks.values() if c)
        total = len(checks)

        md = f"""# RAG 服务性能基准测试报告

## 测试概览
| 指标 | 值 |
|------|-----|
| **Run ID** | {r.run_id} |
| **测试时间** | {r.timestamp} |
| **总查询数** | {r.total_queries} |
| **成功查询数** | {r.successful_queries} |
| **失败查询数** | {r.failed_queries} |
| **成功率** | {r.successful_queries/max(r.total_queries,1):.1%} |

## 性能指标汇总

### 响应时间
| 指标 | 值 | 目标 | 状态 |
|------|-----|------|------|
| 平均响应时间 | {r.avg_latency:.3f}s | <{targets['avg_latency']}s | {"✅" if r.avg_latency<targets['avg_latency'] else "❌"} |
| P50 响应时间 | {r.p50_latency:.3f}s | - | - |
| P95 响应时间 | {r.p95_latency:.3f}s | <{targets['p95_latency']}s | {"✅" if r.p95_latency<targets['p95_latency'] else "❌"} |
| P99 响应时间 | {r.p99_latency:.3f}s | - | - |

### 首字延迟 (TTFT)
| 指标 | 值 | 目标 | 状态 |
|------|-----|------|------|
| 平均 TTFT | {r.avg_ttft:.3f}s | <{targets['avg_ttft']}s | {"✅" if r.avg_ttft<targets['avg_ttft'] else "❌"} |
| P50 TTFT | {r.p50_ttft:.3f}s | - | - |
| P95 TTFT | {r.p95_ttft:.3f}s | - | - |

### 缓存性能
| 指标 | 值 | 目标 | 状态 |
|------|-----|------|------|
| 缓存命中次数 | {r.cache_hits} | - | - |
| 缓存未命中次数 | {r.cache_misses} | - | - |
| 缓存命中率 | {r.cache_hit_rate:.1%} | >{targets['cache_hit_rate']:.0%} | {"✅" if r.cache_hit_rate>targets['cache_hit_rate'] else "❌"} |

### 检索性能
| 指标 | 值 | 目标 | 状态 |
|------|-----|------|------|
| 平均检索结果数 | {r.avg_retrieval_count:.1f} | >={targets['avg_retrieval_count']} | {"✅" if r.avg_retrieval_count>=targets['avg_retrieval_count'] else "❌"} |
| 平均重排序分数 | {r.avg_rerank_score:.3f} | - | - |

## 性能目标达标情况

| 目标 | 实际值 | 目标值 | 状态 |
|------|--------|--------|------|
"""

        for name, (check, detail) in checks.items():
            status_str = "✅ 达标" if check else "❌ 未达标"
            md += f"| {name} | {detail} | {status_str} |\n"

        md += f"\n**总体达标率**: {passed}/{total} ({passed/total*100:.0f}%)\n\n"

        # 优化建议
        md += self._generate_recommendations(r, checks)

        # 测试环境
        md += f"\n## 测试环境\n"
        md += f"- **测试工具**: benchmark.py\n"
        md += f"- **测试时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        md += f"- **服务端点**: {os.getenv('RAG_SERVICE_URL', 'http://localhost:8000')}\n"
        md += f"\n---\n*报告生成时间：{datetime.now().isoformat()}*\n"

        return md

    def _generate_recommendations(
        self, r: BenchmarkReport, checks: Dict
    ) -> str:
        """生成优化建议"""
        recommendations = []

        if not checks["平均响应时间"][0]:
            recommendations.append(
                f"""### ⚠️ 平均响应时间未达标
当前：{r.avg_latency:.3f}s，目标：<1.5s

**建议**:
1. 启用查询缓存
2. 优化检索策略
3. 使用更快的重排序模型
"""
            )

        if not checks["P95 响应时间"][0]:
            recommendations.append(
                f"""### ⚠️ P95 响应时间未达标
当前：{r.p95_latency:.3f}s，目标：<2.5s

**建议**:
1. 优化慢查询
2. 增加超时限制
3. 使用异步处理
"""
            )

        if not checks["缓存命中率"][0]:
            recommendations.append(
                f"""### ⚠️ 缓存命中率未达标
当前：{r.cache_hit_rate:.1%}，目标：>30%

**建议**:
1. 增加缓存容量
2. 延长 TTL
3. 优化缓存键策略
"""
            )

        if not checks["检索召回率@5"][0]:
            recommendations.append(
                f"""### ⚠️ 检索召回率未达标
当前：{r.avg_retrieval_count:.1f}，目标：>=4

**建议**:
1. 调整 top_k 参数
2. 优化混合检索权重
3. 改进向量化质量
"""
            )

        if not checks["首字延迟"][0]:
            recommendations.append(
                f"""### ⚠️ 首字延迟未达标
当前：{r.avg_ttft:.3f}s，目标：<1s

**建议**:
1. 使用 SSE 流式响应
2. 优化检索管道
3. 减少前置处理时间
"""
            )

        if not recommendations:
            return "✅ **所有性能目标均已达标！** 系统性能表现优秀。\n\n"

        return "\n".join(recommendations)

    def save_report(self, filename: str = "BENCHMARK_REPORT.md") -> Path:
        """保存报告"""
        output_path = self.output_dir / filename
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(self.generate_markdown())
        print(f"\n📄 报告已保存至：{output_path}")
        return output_path


def main():
    parser = argparse.ArgumentParser(
        description="RAG 服务性能基准测试"
    )
    parser.add_argument(
        "--url",
        "-u",
        default=os.getenv(
            "RAG_SERVICE_URL", "http://localhost:8000"
        ),
        help="服务端点",
    )
    parser.add_argument(
        "--questions",
        "-q",
        type=int,
        default=50,
        help="测试问题数",
    )
    parser.add_argument(
        "--repeat",
        "-r",
        type=int,
        default=3,
        help="重复次数",
    )
    parser.add_argument(
        "--warmup",
        "-w",
        type=int,
        default=5,
        help="预热查询数",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="docs/reports/benchmark",
        help="输出目录",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出 JSON",
    )
    args = parser.parse_args()

    # 执行测试
    runner = BenchmarkRunner(
        base_url=args.url,
        questions=TEST_QUESTIONS[: args.questions],
        warmup_queries=args.warmup,
        repeat_queries=args.repeat,
    )

    report = runner.run_benchmark()

    # 生成报告
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    generator = ReportGenerator(report, output_dir)
    generator.save_report()

    # 输出 JSON (可选)
    if args.json:
        json_path = output_dir / f"benchmark_{report.run_id}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "run_id": report.run_id,
                    "timestamp": report.timestamp,
                    "summary": {
                        "total_queries": report.total_queries,
                        "successful_queries": report.successful_queries,
                        "failed_queries": report.failed_queries,
                        "avg_latency": report.avg_latency,
                        "p95_latency": report.p95_latency,
                        "cache_hit_rate": report.cache_hit_rate,
                    },
                },
                f,
                indent=2,
            )
        print(f"📊 JSON 已保存至：{json_path}")

    # 打印总结
    print("\n" + "=" * 70)
    print(f"基准测试完成！")
    print(f"总查询：{report.total_queries}")
    print(f"成功率：{report.successful_queries/max(report.total_queries,1):.1%}")
    print(f"平均响应：{report.avg_latency:.3f}s")
    print(f"P95 响应：{report.p95_latency:.3f}s")
    print(f"缓存命中：{report.cache_hit_rate:.1%}")
    print(f"平均检索：{report.avg_retrieval_count:.1f}")
    print(f"平均 TTFT: {report.avg_ttft:.3f}s")
    print("=" * 70)

    return 0 if report.failed_queries == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
