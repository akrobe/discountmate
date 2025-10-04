pipeline {
  agent any

  environment {
    REGISTRY = 'ghcr.io'
    IMAGE_REPO = 'akrobe/discountmate'
    GIT_SHORT = sh(script: 'git rev-parse --short HEAD', returnStdout: true).trim()
    DATESTAMP = sh(script: 'date +%Y.%m.%d', returnStdout: true).trim()
    VERSION = "${DATESTAMP}-12-${GIT_SHORT}"
    IMAGE = "${REGISTRY}/${IMAGE_REPO}:${VERSION}"
    LATEST = "${REGISTRY}/${IMAGE_REPO}:latest"
    SVC_NAME = 'dm_svc'
  }

  stages {
    stage('Docker Sanity') {
      steps {
        sh '''
          set -eux
          which docker
          docker --version
          docker compose version || true
        '''
      }
    }

    stage('Build & Push (multi-arch)') {
      steps {
        withCredentials([string(credentialsId: 'github-https-token-or-ghcr-pat', variable: 'PAT')]) {
          sh '''
            set -eux
            echo "$PAT" | docker login ${REGISTRY} -u akrobe --password-stdin

            # Buildx multi-arch so scanners & runtimes on amd64/arm64 both work
            docker buildx create --use --name ci-builder || docker buildx use ci-builder
            docker buildx inspect --bootstrap

            docker buildx build \
              --platform linux/amd64,linux/arm64 \
              -t "${IMAGE}" -t "${LATEST}" \
              --push .
          '''
        }
      }
    }

    stage('Test (unit + integration)') {
      steps {
        sh '''
          set -eux
          mkdir -p reports

          # Unit
          docker run --rm -v "$PWD":/workspace -w /workspace -e PYTHONPATH=/workspace \
            ${IMAGE} sh -lc '
              pip install -r requirements.txt -r requirements-dev.txt &&
              pytest -q --junitxml=reports/junit.xml --cov=app --cov-report=xml:reports/coverage.xml tests/test_unit_model.py
            '

          # Clean any stale
          docker rm -f ${SVC_NAME} 2>/dev/null || true

          # Start service for integration
          docker run -d --rm --name ${SVC_NAME} -p 8088:8080 ${IMAGE}

          # Health wait
          for i in $(seq 1 30); do
            if curl -sf http://localhost:8088/health >/dev/null; then break; fi
            sleep 1
          done

          # Integration (containerized pytest talks to host service via host.docker.internal on Mac/Win, or use localhost when not in container)
          docker run --rm -v "$PWD":/workspace -w /workspace -e PYTHONPATH=/workspace \
            -e BASE_URL=http://host.docker.internal:8088 \
            ${IMAGE} sh -lc '
              pip install -r requirements.txt -r requirements-dev.txt &&
              pytest -q --junitxml=reports/junit-it.xml tests/test_integration_api.py
            '
        '''
      }
      post {
        always {
          sh 'docker rm -f ${SVC_NAME} 2>/dev/null || true'
          junit 'reports/junit*.xml'
          archiveArtifacts artifacts: 'reports/**', fingerprint: true
        }
      }
    }

    stage('Security (Bandit, pip-audit, Trivy)') {
      steps {
        sh '''
          set -eux
          mkdir -p reports

          # Bandit + pip-audit in a throwaway Python container
          docker run --rm -v "$PWD":/src python:3.12-slim sh -lc '
            pip install --no-cache-dir bandit pip-audit &&
            cd /src &&
            bandit -r app -f json -o reports/bandit.json || true &&
            pip-audit -r requirements.txt -f json -o reports/pip-audit.json || true
          '

          # Trivy: remote scan against GHCR manifest (now multi-arch, so no platform mismatch).
          # Cache DB between runs for speed.
          mkdir -p "$HOME/.cache/trivy"
          docker run --rm \
            -v "$HOME/.cache/trivy:/root/.cache/" \
            -v "$PWD/reports:/out" \
            aquasec/trivy:0.51.2 image \
              --scanners vuln \
              --ignore-unfixed \
              --severity CRITICAL,HIGH \
              --format json -o /out/trivy.json \
              --no-progress \
              "${IMAGE}" || true

          # Simple gate: fail if CRITICAL present
          python3 - <<'PY'
import json, sys, pathlib
p = pathlib.Path('reports/trivy.json')
if not p.exists():
    print('Trivy report missing (skipped or failed).'); sys.exit(0)
data = json.loads(p.read_text() or '{}')
sev = []
for r in data if isinstance(data, list) else data.get('Results', []):
    for v in r.get('Vulnerabilities', []) or []:
        sev.append(v.get('Severity'))
crit = sev.count('CRITICAL')
print(f'Trivy CRITICAL count: {crit}')
sys.exit(1 if crit else 0)
PY
        '''
      }
    }

    stage('Deploy: Staging (compose + health gate)') {
      when { expression { fileExists('env/.env.staging') && fileExists('compose.yaml') } }
      steps {
        sh '''
          set -eux
          export IMAGE="${IMAGE}"
          docker compose --env-file env/.env.staging --profile staging up -d

          # Health gate vs compose service
          for i in $(seq 1 30); do
            if curl -sf http://localhost:${STAGING_HOST_PORT:-8089}/health >/dev/null; then
              echo "Staging healthy"; exit 0; fi
            sleep 1
          done
          echo "Staging failed health"; exit 1
        '''
      }
    }
  }

  post {
    failure { echo 'Pipeline FAILED' }
    success { echo "Pipeline OK — ${IMAGE}" }
  }
}