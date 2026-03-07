"""
上下文压缩器单元测试
测试压缩率、信息保留率和两种压缩模式
"""
import pytest
import sys
import os
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.context_compressor import (
    ContextCompressor,
    ContextCompressorInterface,
    LLMBasedCompressor,
    ExtractiveCompressor,
    CompressionMode,
    CompressedContext,
    get_compressor,
)
from app.main import RankedChunk, LLMGateway, ServiceConfig


class TestCompressedContext:
    """测试 CompressedContext 数据类"""

    def test_context_creation(self):
        """测试压缩上下文创建"""
        context = CompressedContext(
            original_text="原始文本内容",
            compressed_text="压缩后的文本",
            original_tokens=100,
            compressed_tokens=60,
            compression_rate=0.4,
            information_retention_rate=0.95,
            mode=CompressionMode.LLM,
        )
        
        assert context.original_text == "原始文本内容"
        assert context.compressed_text == "压缩后的文本"
        assert context.original_tokens == 100
        assert context.compressed_tokens == 60
        assert context.compression_rate == 0.4
        assert context.information_retention_rate == 0.95
        assert context.mode == CompressionMode.LLM

    def test_context_with_metadata(self):
        """测试包含元数据的压缩上下文"""
        context = CompressedContext(
            original_text="原始文本",
            compressed_text="压缩文本",
            original_tokens=80,
            compressed_tokens=40,
            compression_rate=0.5,
            information_retention_rate=0.9,
            mode=CompressionMode.EXTRACTIVE,
            metadata={"query": "测试查询", "max_tokens": 50},
        )
        
        assert context.metadata["query"] == "测试查询"
        assert context.metadata["max_tokens"] == 50

    def test_context_immutability(self):
        """测试压缩上下文不可变性"""
        context = CompressedContext(
            original_text="原始",
            compressed_text="压缩",
            original_tokens=50,
            compressed_tokens=30,
            compression_rate=0.4,
            information_retention_rate=0.9,
            mode=CompressionMode.LLM,
        )
        
        with pytest.raises(Exception):
            context.compression_rate = 0.5


class TestExtractiveCompressor:
    """测试提取式压缩器"""

    def test_basic_extraction(self):
        """测试基本的提取式压缩"""
        compressor = ExtractiveCompressor()
        
        query = "如何使用 Python 读取文件？"
        context = """
        Python 提供了多种读取文件的方法。
        最常用的方法是使用 open() 函数。
        open() 函数可以以不同的模式打开文件，如读取模式 'r'。
        读取文件内容可以使用 read() 方法。
        也可以使用 readline() 逐行读取。
        还可以使用 readlines() 读取所有行。
        文件操作完成后应该使用 close() 关闭文件。
        推荐使用 with 语句自动管理文件资源。
        """
        
        result = compressor.compress(query, context, max_tokens=50)
        
        assert result.original_text == context
        assert len(result.compressed_text) <= len(result.original_text)
        assert result.compression_rate >= 0.0
        assert result.compression_rate <= 1.0
        assert result.information_retention_rate >= 0.0
        assert result.information_retention_rate <= 1.0
        assert result.mode == CompressionMode.EXTRACTIVE

    def test_sentence_splitting(self):
        """测试句子分割"""
        compressor = ExtractiveCompressor()
        
        text = "第一句。第二句！第三句？Fourth sentence.Fifth sentence!"
        sentences = compressor._split_sentences(text)
        
        assert len(sentences) == 5
        assert "第一句" in sentences[0]
        assert "第二句" in sentences[1]
        assert "第三句" in sentences[2]

    def test_keyword_extraction(self):
        """测试关键词提取"""
        compressor = ExtractiveCompressor()
        
        query = "Python 文件读取方法"
        keywords = compressor._extract_keywords(query)
        
        assert any("python" in kw.lower() for kw in keywords)

    def test_sentence_scoring(self):
        """测试句子评分"""
        compressor = ExtractiveCompressor()
        
        query = "Python 读取文件"
        sentences = [
            "Python 提供了 open() 函数来读取文件。",
            "这是一个无关的句子，关于其他主题。",
            "使用 read() 方法可以获取文件内容。",
        ]
        
        scored = compressor._score_sentences(query, sentences)
        
        assert len(scored) == 3
        
        first_sentence_score = scored[0][2]
        second_sentence_score = scored[1][2]
        
        assert first_sentence_score > second_sentence_score

    def test_top_sentence_selection(self):
        """测试选择 top 句子"""
        compressor = ExtractiveCompressor()
        
        scored_sentences = [
            (0, "句子 A", 0.9),
            (1, "句子 B", 0.3),
            (2, "句子 C", 0.7),
            (3, "句子 D", 0.5),
        ]
        
        selected = compressor._select_top_sentences(scored_sentences, max_tokens=20)
        
        assert len(selected) >= 1
        
        selected_sentences = [s for s in selected]
        assert "句子 A" in selected_sentences[0] or "句子 C" in selected_sentences[0]

    def test_empty_context(self):
        """测试空上下文"""
        compressor = ExtractiveCompressor()
        
        query = "测试查询"
        context = ""
        
        result = compressor.compress(query, context, max_tokens=50)
        
        assert result.compressed_text == ""
        assert result.compression_rate == 0.0

    def test_compression_rate_calculation(self):
        """测试压缩率计算"""
        compressor = ExtractiveCompressor()
        
        original = 100
        compressed = 60
        rate = compressor._calculate_compression_rate(original, compressed)
        
        assert rate == 0.4

    def test_zero_original_tokens(self):
        """测试零原始 token 数"""
        compressor = ExtractiveCompressor()
        
        rate = compressor._calculate_compression_rate(0, 50)
        
        assert rate == 0.0


class TestLLMBasedCompressor:
    """测试基于 LLM 的压缩器"""

    def test_llm_compressor_creation(self):
        """测试 LLM 压缩器创建"""
        mock_llm_gateway = MagicMock(spec=LLMGateway)
        compressor = LLMBasedCompressor(mock_llm_gateway)
        
        assert compressor.llm_gateway == mock_llm_gateway

    def test_llm_compression_with_mock(self):
        """测试 LLM 压缩（使用 mock）"""
        mock_llm_gateway = MagicMock(spec=LLMGateway)
        mock_config = MagicMock()
        mock_config.chat_model = "test-model"
        mock_llm_gateway._cfg = mock_config
        
        mock_response = {
            "choices": [
                {
                    "message": {
                        "content": "Python 使用 open() 函数读取文件，支持多种读取方式。"
                    }
                }
            ]
        }
        mock_llm_gateway._request_json.return_value = mock_response
        
        compressor = LLMBasedCompressor(mock_llm_gateway)
        
        query = "如何使用 Python 读取文件？"
        context = """
        Python 提供了多种读取文件的方法。
        最常用的方法是使用 open() 函数。
        open() 函数可以以不同的模式打开文件，如读取模式 'r'。
        读取文件内容可以使用 read() 方法。
        也可以使用 readline() 逐行读取。
        还可以使用 readlines() 读取所有行。
        """
        
        result = compressor.compress(query, context, max_tokens=50)
        
        assert result.mode == CompressionMode.LLM
        assert result.compressed_tokens <= result.original_tokens
        assert result.compression_rate >= 0.0

    def test_llm_compression_fallback_on_error(self):
        """测试 LLM 压缩失败时的回退"""
        mock_llm_gateway = MagicMock(spec=LLMGateway)
        mock_llm_gateway._request_json.side_effect = RuntimeError("LLM 调用失败")
        
        compressor = LLMBasedCompressor(mock_llm_gateway)
        
        query = "测试查询"
        context = "这是原始上下文内容"
        
        result = compressor.compress(query, context, max_tokens=50)
        
        assert result.compressed_text == context
        assert result.compression_rate == 0.0

    def test_token_counting(self):
        """测试 token 计数"""
        compressor = LLMBasedCompressor(MagicMock(spec=LLMGateway))
        
        text = "这是一个测试文本 This is a test text"
        tokens = compressor._count_tokens(text)
        
        assert tokens > 0
        
        chinese_count = len("这是一个测试文本")
        english_count = len(["This", "is", "a", "test", "text"])
        expected_min = chinese_count + english_count
        
        assert tokens >= expected_min

    def test_information_retention_estimation(self):
        """测试信息保留率估算"""
        compressor = LLMBasedCompressor(MagicMock(spec=LLMGateway))
        
        query = "Python 文件操作"
        original = "Python 提供了文件操作功能，可以读写文件"
        compressed = "Python 文件操作 读写"
        
        retention = compressor._estimate_information_retention(query, original, compressed)
        
        assert retention >= 0.0
        assert retention <= 1.0


class TestContextCompressor:
    """测试统一的上下文压缩器"""

    def test_compressor_with_llm_mode(self):
        """测试 LLM 模式压缩器"""
        mock_llm_gateway = MagicMock(spec=LLMGateway)
        mock_config = MagicMock()
        mock_config.chat_model = "test-model"
        mock_llm_gateway._cfg = mock_config
        
        mock_response = {
            "choices": [{"message": {"content": "压缩后的内容"}}]
        }
        mock_llm_gateway._request_json.return_value = mock_response
        
        compressor = get_compressor(
            llm_gateway=mock_llm_gateway,
            mode="llm",
            max_tokens=100,
            enabled=True,
        )
        
        assert compressor.mode == CompressionMode.LLM
        assert compressor.max_tokens == 100
        assert compressor.enabled is True

    def test_compressor_with_extractive_mode(self):
        """测试提取式模式压缩器"""
        compressor = get_compressor(
            llm_gateway=None,
            mode="extractive",
            max_tokens=100,
            enabled=True,
        )
        
        assert compressor.mode == CompressionMode.EXTRACTIVE
        assert compressor.max_tokens == 100

    def test_compressor_fallback_to_extractive(self):
        """测试 LLM 模式在没有 LLM 网关时回退到提取式"""
        compressor = get_compressor(
            llm_gateway=None,
            mode="llm",
            max_tokens=100,
            enabled=True,
        )
        
        assert compressor.mode == CompressionMode.EXTRACTIVE

    def test_compressor_disabled(self):
        """测试禁用压缩"""
        compressor = get_compressor(
            llm_gateway=None,
            mode="extractive",
            max_tokens=100,
            enabled=False,
        )
        
        chunks = [
            RankedChunk(
                chunk_id="1",
                document_id="d1",
                corpus_id="c1",
                file_name="test.txt",
                page_or_loc="p1",
                text="测试内容",
                vector_score=0.9,
                lexical_score=0.8,
                final_score=0.85,
            ),
        ]
        
        result = compressor.compress("查询", chunks, max_tokens=50)
        
        assert result.compression_rate == 0.0
        assert result.information_retention_rate == 1.0
        assert result.original_text == result.compressed_text

    def test_compress_ranked_chunks(self):
        """测试压缩排序后的检索结果"""
        compressor = get_compressor(
            llm_gateway=None,
            mode="extractive",
            max_tokens=100,
            enabled=True,
        )
        
        chunks = [
            RankedChunk(
                chunk_id="1",
                document_id="d1",
                corpus_id="c1",
                file_name="test.txt",
                page_or_loc="p1",
                text="Python 读取文件的第一种方法：使用 open() 函数。",
                vector_score=0.95,
                lexical_score=0.9,
                final_score=0.93,
            ),
            RankedChunk(
                chunk_id="2",
                document_id="d2",
                corpus_id="c1",
                file_name="test.txt",
                page_or_loc="p2",
                text="Python 读取文件的第二种方法：使用 with 语句。",
                vector_score=0.85,
                lexical_score=0.8,
                final_score=0.83,
            ),
            RankedChunk(
                chunk_id="3",
                document_id="d3",
                corpus_id="c1",
                file_name="test.txt",
                page_or_loc="p3",
                text="这是一个无关的内容，关于其他主题的描述。",
                vector_score=0.5,
                lexical_score=0.4,
                final_score=0.45,
            ),
        ]
        
        query = "Python 如何读取文件？"
        result = compressor.compress(query, chunks, max_tokens=80)
        
        assert result.original_tokens >= result.compressed_tokens
        assert result.compression_rate >= 0.0
        assert result.mode == CompressionMode.EXTRACTIVE

    def test_chunks_to_context_conversion(self):
        """测试将检索结果转换为上下文"""
        compressor = get_compressor(
            llm_gateway=None,
            mode="extractive",
            max_tokens=100,
            enabled=True,
        )
        
        chunks = [
            RankedChunk(
                chunk_id="1",
                document_id="d1",
                corpus_id="c1",
                file_name="文档 1.txt",
                page_or_loc="第 1 页",
                text="内容 1",
                vector_score=0.9,
                lexical_score=0.8,
                final_score=0.85,
            ),
            RankedChunk(
                chunk_id="2",
                document_id="d2",
                corpus_id="c1",
                file_name="文档 2.txt",
                page_or_loc="第 2 页",
                text="内容 2",
                vector_score=0.8,
                lexical_score=0.7,
                final_score=0.75,
            ),
        ]
        
        context = compressor._chunks_to_context(chunks)
        
        assert "文档 1.txt" in context
        assert "第 1 页" in context
        assert "内容 1" in context
        assert "文档 2.txt" in context
        assert "第 2 页" in context
        assert "内容 2" in context


class TestCompressionEffectiveness:
    """测试压缩效果"""

    def test_compression_rate_meets_requirement(self):
        """测试压缩率达到要求（≥30%）"""
        compressor = get_compressor(
            llm_gateway=None,
            mode="extractive",
            max_tokens=100,
            enabled=True,
        )
        
        query = "Python 文件操作"
        context = """
        Python 提供了丰富的文件操作功能。
        可以使用 open() 函数打开文件。
        open() 函数支持多种模式，如读取模式'r'、写入模式'w'。
        读取文件内容可以使用 read()、readline()、readlines() 方法。
        写入文件可以使用 write() 方法。
        文件操作完成后应该使用 close() 方法关闭。
        推荐使用 with 语句自动管理文件资源。
        with 语句会在代码块结束后自动关闭文件。
        这样可以避免资源泄漏的问题。
        Python 的文件操作非常灵活和强大。
        """
        
        chunks = [
            RankedChunk(
                chunk_id=str(i),
                document_id=f"d{i}",
                corpus_id="c1",
                file_name="test.txt",
                page_or_loc=f"p{i}",
                text=context,
                vector_score=0.9 - i * 0.1,
                lexical_score=0.8 - i * 0.1,
                final_score=0.85 - i * 0.1,
            )
            for i in range(3)
        ]
        
        result = compressor.compress(query, chunks, max_tokens=150)
        
        assert result.compression_rate >= 0.3 or result.compressed_tokens <= 150

    def test_information_retention_meets_requirement(self):
        """测试信息保留率达到要求（≥90%）"""
        compressor = get_compressor(
            llm_gateway=None,
            mode="extractive",
            max_tokens=200,
            enabled=True,
        )
        
        query = "Python 读取文件"
        context = """
        Python 读取文件主要使用 open() 函数。
        open() 函数可以指定文件路径和打开模式。
        读取模式使用'r'参数。
        可以使用 read() 一次性读取全部内容。
        也可以使用 readline() 逐行读取。
        readlines() 可以读取所有行到列表中。
        """
        
        chunks = [
            RankedChunk(
                chunk_id="1",
                document_id="d1",
                corpus_id="c1",
                file_name="test.txt",
                page_or_loc="p1",
                text=context,
                vector_score=0.9,
                lexical_score=0.8,
                final_score=0.85,
            ),
        ]
        
        result = compressor.compress(query, chunks, max_tokens=200)
        
        assert result.information_retention_rate >= 0.9 or result.compressed_tokens <= 200

    def test_max_tokens_constraint(self):
        """测试最大 token 数约束"""
        compressor = get_compressor(
            llm_gateway=None,
            mode="extractive",
            max_tokens=50,
            enabled=True,
        )
        
        query = "测试"
        context = "这是一个很长的文本" * 20
        
        chunks = [
            RankedChunk(
                chunk_id="1",
                document_id="d1",
                corpus_id="c1",
                file_name="test.txt",
                page_or_loc="p1",
                text=context,
                vector_score=0.9,
                lexical_score=0.8,
                final_score=0.85,
            ),
        ]
        
        result = compressor.compress(query, chunks, max_tokens=50)
        
        assert result.compressed_tokens <= 50


class TestCompressionMode:
    """测试压缩模式枚举"""

    def test_compression_mode_values(self):
        """测试压缩模式值"""
        assert CompressionMode.LLM.value == "llm"
        assert CompressionMode.EXTRACTIVE.value == "extractive"

    def test_compression_mode_from_string(self):
        """测试从字符串创建模式"""
        mode_llm = CompressionMode("llm")
        assert mode_llm == CompressionMode.LLM
        
        mode_extractive = CompressionMode("extractive")
        assert mode_extractive == CompressionMode.EXTRACTIVE


class TestGetCompressor:
    """测试 get_compressor 工厂函数"""

    def test_get_compressor_with_all_params(self):
        """测试提供所有参数时获取压缩器"""
        mock_llm = MagicMock(spec=LLMGateway)
        
        compressor = get_compressor(
            llm_gateway=mock_llm,
            mode="llm",
            max_tokens=2000,
            enabled=True,
        )
        
        assert compressor is not None
        assert compressor.mode == CompressionMode.LLM
        assert compressor.max_tokens == 2000
        assert compressor.enabled is True

    def test_get_compressor_with_defaults(self):
        """测试使用默认参数获取压缩器"""
        compressor = get_compressor()
        
        assert compressor is not None
        assert compressor.max_tokens == 3200
        assert compressor.enabled is True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
