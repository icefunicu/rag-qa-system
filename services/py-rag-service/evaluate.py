#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RAG 评估脚本

用于离线评估 RAG 系统的性能，支持批量评估和 A/B 测试。

使用方法:
    # 批量评估
    python evaluate.py --dataset evaluation_dataset.json --output evaluation_report.json
    
    # A/B 测试
    python evaluate.py --ab-test --dataset-a config_a_samples.json --dataset-b config_b_samples.json
    
    # 生成报告
    python evaluate.py --report evaluation_result.json --output evaluation_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.evaluator import (
    RAGEvaluator,
    EvaluationSample,
    BatchEvaluationResult,
    ABTestResult,
    get_evaluator,
)


def load_dataset(dataset_path: str) -> List[Dict[str, Any]]:
    """加载评估数据集"""
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)
    
    if "samples" in dataset:
        return dataset["samples"]
    elif isinstance(dataset, list):
        return dataset
    else:
        raise ValueError(f"Invalid dataset format: {dataset_path}")


def run_batch_evaluation(
    dataset_path: str,
    output_path: str,
    ragas_api_key: Optional[str] = None,
) -> BatchEvaluationResult:
    """运行批量评估"""
    print(f"加载数据集：{dataset_path}")
    samples = load_dataset(dataset_path)
    print(f"加载了 {len(samples)} 个样本")

    evaluator = get_evaluator(ragas_api_key)
    
    evaluation_samples = [
        EvaluationSample(
            question=sample["question"],
            answer=sample["answer"],
            contexts=sample["contexts"],
            ground_truth=sample["ground_truth"],
            metadata=sample.get("metadata", {}),
        )
        for sample in samples
    ]

    print("\n开始批量评估...")
    result = evaluator.evaluate_batch(evaluation_samples)

    print(f"\n评估完成:")
    print(f"  总样本数：{result.total_samples}")
    print(f"  成功样本数：{result.successful_samples}")
    print(f"  失败样本数：{result.failed_samples}")
    print(f"\n平均指标:")
    for metric_name, value in result.avg_metrics.items():
        print(f"  {metric_name}: {value:.4f}")

    print(f"\n生成评估报告：{output_path}")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    evaluator.generate_report(result, output_path)

    return result


def run_ab_test(
    dataset_a_path: str,
    dataset_b_path: str,
    output_path: str,
    config_a_name: str = "Config A",
    config_b_name: str = "Config B",
    ragas_api_key: Optional[str] = None,
) -> ABTestResult:
    """运行 A/B 测试"""
    print(f"加载配置 A 数据集：{dataset_a_path}")
    samples_a = load_dataset(dataset_a_path)
    print(f"加载了 {len(samples_a)} 个样本")

    print(f"\n加载配置 B 数据集：{dataset_b_path}")
    samples_b = load_dataset(dataset_b_path)
    print(f"加载了 {len(samples_b)} 个样本")

    evaluator = get_evaluator(ragas_api_key)

    evaluation_samples_a = [
        EvaluationSample(
            question=sample["question"],
            answer=sample["answer"],
            contexts=sample["contexts"],
            ground_truth=sample["ground_truth"],
            metadata=sample.get("metadata", {}),
        )
        for sample in samples_a
    ]

    evaluation_samples_b = [
        EvaluationSample(
            question=sample["question"],
            answer=sample["answer"],
            contexts=sample["contexts"],
            ground_truth=sample["ground_truth"],
            metadata=sample.get("metadata", {}),
        )
        for sample in samples_b
    ]

    print(f"\n开始 A/B 测试...")
    print(f"  配置 A: {config_a_name}")
    print(f"  配置 B: {config_b_name}")

    result = evaluator.ab_test(
        evaluation_samples_a,
        evaluation_samples_b,
        config_a_name=config_a_name,
        config_b_name=config_b_name,
    )

    print(f"\nA/B 测试完成:")
    print(f"  获胜者：{result.winner}")
    print(f"\n指标对比:")
    for metric_name, comparison in result.metrics_comparison.items():
        print(f"  {metric_name}:")
        print(f"    {config_a_name}: {comparison['config_a']:.4f}")
        print(f"    {config_b_name}: {comparison['config_b']:.4f}")
        print(f"    差异：{comparison['diff']:+.4f} ({comparison['diff_percent']:+.2f}%)")
        print(f"    统计显著性：{'是' if result.statistical_significance[metric_name] else '否'}")

    print(f"\n生成 A/B 测试报告：{output_path}")
    save_ab_test_report(result, output_path)

    return result


def generate_report(
    evaluation_result_path: str,
    output_path: str,
    ragas_api_key: Optional[str] = None,
):
    """生成评估报告"""
    print(f"加载评估结果：{evaluation_result_path}")
    
    with open(evaluation_result_path, "r", encoding="utf-8") as f:
        evaluation_result = json.load(f)

    evaluator = get_evaluator(ragas_api_key)

    individual_results = []
    for item in evaluation_result.get("individual_results", []):
        from app.evaluator import EvaluationResult, EvaluationMetrics
        individual_results.append(
            EvaluationResult(
                sample_id=item["sample_id"],
                question=item["question"],
                answer=item.get("answer", ""),
                contexts=item.get("contexts", []),
                ground_truth=item.get("ground_truth", ""),
                metrics=EvaluationMetrics(
                    context_precision=item["metrics"]["context_precision"],
                    context_recall=item["metrics"]["context_recall"],
                    faithfulness=item["metrics"]["faithfulness"],
                    answer_relevancy=item["metrics"]["answer_relevancy"],
                    overall_score=item["metrics"]["overall_score"],
                ),
            )
        )

    avg_metrics = evaluation_result.get("avg_metrics", {})
    
    batch_result = BatchEvaluationResult(
        run_id=evaluation_result.get("run_id", "unknown"),
        total_samples=evaluation_result.get("total_samples", len(individual_results)),
        successful_samples=evaluation_result.get("successful_samples", len(individual_results)),
        failed_samples=evaluation_result.get("failed_samples", 0),
        avg_metrics=avg_metrics,
        individual_results=individual_results,
        timestamp=evaluation_result.get("timestamp", datetime.now().isoformat()),
    )

    print(f"生成报告：{output_path}")
    evaluator.generate_report(batch_result, output_path)


def save_ab_test_report(result: ABTestResult, output_path: str):
    """保存 A/B 测试报告"""
    report = {
        "test_id": result.test_id,
        "timestamp": result.timestamp,
        "configs": {
            "config_a": result.config_a_name,
            "config_b": result.config_b_name,
        },
        "winner": result.winner,
        "metrics_comparison": result.metrics_comparison,
        "statistical_significance": result.statistical_significance,
        "summary": {
            "winner": result.winner,
            "metrics_won": sum(
                1 for v in result.metrics_comparison.values()
                if (result.config_a_name == result.winner and v["config_a"] > v["config_b"]) or
                   (result.config_b_name == result.winner and v["config_b"] > v["config_a"])
            ),
        },
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="RAG 评估脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--dataset",
        type=str,
        help="评估数据集路径（JSON 格式）",
    )

    parser.add_argument(
        "--dataset-a",
        type=str,
        help="A/B 测试中配置 A 的数据集路径",
    )

    parser.add_argument(
        "--dataset-b",
        type=str,
        help="A/B 测试中配置 B 的数据集路径",
    )

    parser.add_argument(
        "--output",
        type=str,
        default="docs/reports/evaluation/evaluation_report.json",
        help="输出报告路径（默认：docs/reports/evaluation/evaluation_report.json）",
    )

    parser.add_argument(
        "--ab-test",
        action="store_true",
        help="运行 A/B 测试",
    )

    parser.add_argument(
        "--report",
        type=str,
        help="从现有评估结果生成报告",
    )

    parser.add_argument(
        "--config-a-name",
        type=str,
        default="Config A",
        help="配置 A 的名称（默认：Config A）",
    )

    parser.add_argument(
        "--config-b-name",
        type=str,
        default="Config B",
        help="配置 B 的名称（默认：Config B）",
    )

    parser.add_argument(
        "--ragas-api-key",
        type=str,
        help="RAGAS API 密钥（可选，用于云端评估）",
    )

    args = parser.parse_args()

    try:
        if args.ab_test:
            if not args.dataset_a or not args.dataset_b:
                print("错误：A/B 测试需要指定 --dataset-a 和 --dataset-b")
                sys.exit(1)

            run_ab_test(
                args.dataset_a,
                args.dataset_b,
                args.output,
                config_a_name=args.config_a_name,
                config_b_name=args.config_b_name,
                ragas_api_key=args.ragas_api_key,
            )

        elif args.report:
            generate_report(
                args.report,
                args.output,
                ragas_api_key=args.ragas_api_key,
            )

        elif args.dataset:
            run_batch_evaluation(
                args.dataset,
                args.output,
                ragas_api_key=args.ragas_api_key,
            )

        else:
            print("错误：请指定 --dataset、--ab-test 或 --report")
            parser.print_help()
            sys.exit(1)

        print("\n评估完成！")

    except Exception as e:
        print(f"\n错误：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
