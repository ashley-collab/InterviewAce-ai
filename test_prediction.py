from services.ml_model import predict_answer

answer = """
Python is a high-level interpreted programming language.
It supports object-oriented programming.
"""

result = predict_answer(answer)

print(result)