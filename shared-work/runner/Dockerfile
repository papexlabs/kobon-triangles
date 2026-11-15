# The throwaway environment in which Papex Labs fetches and re-checks linked proofs.
# Build from the repository root:   docker build -f shared-work/runner/Dockerfile -t kobon-recheck .
# Run (the job directory holds job.json and receives out.json; no credential goes in):
#   docker run --rm --memory 6g --cpus 2 -v /path/to/job:/job kobon-recheck
FROM debian:stable-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
        build-essential ca-certificates curl python3 xz-utils && rm -rf /var/lib/apt/lists/*
WORKDIR /kobon
COPY . /kobon
RUN cc -std=c99 -DLONGTYPE -O2 -o checker/lrat-check checker/lrat-check.c \
    && python3 -I src/kobon_cnf.py 11 33 --case-b --lex > build/k11_33_caseB.lex.cnf \
    && useradd --create-home recheck && chown -R recheck /kobon
USER recheck
CMD ["python3", "shared-work/runner/recheck_proofs.py", "/job/job.json", "/job/out.json"]
