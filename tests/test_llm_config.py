from ladle_preallocation.llm.config import load_runtime_config


def test_runtime_config_reads_environment_without_dotenv_side_effects():
    config = load_runtime_config(
        {
            "LLM_API_KEY": "sk-test",
            "LLM_API_BASE": "https://example.test",
            "LLM_MODEL": "test-model",
        }
    )

    assert config.configured is True
    assert config.source == "environment"
    assert config.redacted() == {
        "configured": True,
        "source": "environment",
        "api_base": "https://example.test",
        "model": "test-model",
    }
    assert "sk-test" not in str(config.redacted())


def test_runtime_config_marks_missing_key_as_unconfigured():
    config = load_runtime_config({"LLM_API_BASE": "https://example.test"})

    assert config.configured is False
    assert config.source == "unconfigured"
