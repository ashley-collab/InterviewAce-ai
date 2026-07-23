import joblib

model = joblib.load("models/interview_model.pkl")
vectorizer = joblib.load("models/vectorizer.pkl")

print("Model:", type(model))
print("Vectorizer:", type(vectorizer))