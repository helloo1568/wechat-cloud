FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
COPY app.py .
ENV USE_CLOUD_CALL=1
ENV PORT=80
EXPOSE 80
CMD ["python", "app.py"]
