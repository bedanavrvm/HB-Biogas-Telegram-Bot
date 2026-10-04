"""Compatibility import; implementation is owned by Origination."""
from importlib import import_module
import sys
sys.modules[__name__] = import_module('origination.services.generic_jawabu_laf_seed')
