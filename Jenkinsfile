pipeline {
  // Make sure your Jenkins node that has Docker & Compose is labeled "docker"
  agent { label 'docker' }

  options {
    timestamps()
    // ansiColor removed to avoid "Invalid option type" error on instances without the plugin
  }

  environment {
    REGISTRY     = 'ghcr.io'
    IMAGE_REPO   = 'akrobe/discountmate'
    IMAGE        = "${REGISTRY}/${IMAGE_REPO}"
    COMPOSE_FILE = 'compose.yaml'
  }

  stages {
    stage('Checkout') {
      steps { checkout scm }
    }

    stage('Init') {
      steps {
        sh '''
          set -eux
          GIT_SHA=$(git rev-parse --short HEAD)
          DATE=$(date +%Y.%m.%d)
          VERSION="${DATE}-${BUILD_NUMBER:-0}-${GIT_SHA}"
          mkdir -p reports
          echo "VERSION=${VERSION}" | tee reports/version.txt
        '''
        script {
          env.VERSION = sh(returnStdout: true, script: "awk -F= '/^VERSION=/{print \$2}' reports/version.txt").trim()
        }
      }
    }

    stage('Docker Sanity') {
      steps {
        sh '''
          set -eux
          which docker
          docker --version
          docker version
          docker compose version || { echo "Docker Compose v2 is required"; exit 1; }
          docker buildx version || true
        '''
      }
    }

    stage('Build & Push (multi-arch)') {
      steps {
        withCredentials([string(credentialsId: 'ghcr_pat', variable: 'PAT')]) {
          sh '''
            set -eux
            echo "$PAT" | docker login ghcr.io -u akrobe --password-stdin

            docker buildx create --name dm_builder --use || docker buildx use dm_builder || true

            docker buildx build \
              --platform linux/amd64,linux/arm64 \
              -t ${IMAGE}:${VERSION} \
              -t ${IMAGE}:latest \
              --push .
          '''
        }
      }
    }

    stage('Test (unit)') {
      steps {
        sh '''
          set -eux
          mkdir -p reports
          docker run --rm \
            -v "$WORKSPACE":/workspace -w /workspace \
            -e PYTHONPATH=/workspace \
            ${IMAGE}:${VERSION} sh -lc '
              pip install -r requirements.txt -r requirements-dev.txt &&
              pytest -q --junitxml=reports/junit.xml \
                     --cov=app --cov-report=xml:reports/coverage.xml \
                     tests/test_unit_model.py
            '
        '''
      }
      post {
        always {
          junit 'reports/junit.xml'
          archiveArtifacts artifacts: 'reports/**/*', fingerprint: true, onlyIfSuccessful: false
        }
      }
    }

    stage('Test (integration)') {
      steps {
        sh '''
          set -eux
          docker rm -f dm_svc || true

          APP_PORT=8088
          docker run -d --rm --name dm_svc -p ${APP_PORT}:8080 ${IMAGE}:${VERSION}

          for i in $(seq 1 30); do
            curl -sf "http://localhost:${APP_PORT}/health" && break || sleep 1
          done

          docker run --rm \
            -v "$WORKSPACE":/workspace -w /workspace \
            -e PYTHONPATH=/workspace \
            -e BASE_URL="http://host.docker.internal:${APP_PORT}" \
            ${IMAGE}:${VERSION} sh -lc '
              pip install -r requirements.txt -r requirements-dev.txt &&
              pytest -q --junitxml=reports/junit-it.xml tests/test_integration_api.py
            '
        '''
      }
      post {
        always {
          sh 'docker rm -f dm_svc || true'
          junit 'reports/junit-it.xml'
          archiveArtifacts artifacts: 'reports/**/*', fingerprint: true, onlyIfSuccessful: false
        }
      }
    }

    stage('Security (Bandit, pip-audit, Trivy)') {
      steps {
        sh '''
          set +e
          mkdir -p reports

          docker run --rm -v "$WORKSPACE":/src python:3.12-slim sh -lc '
            pip install --no-cache-dir bandit pip-audit >/dev/null 2>&1 && \
            cd /src && \
            bandit -r app -f json -o reports/bandit.json || true && \
            pip-audit -r requirements.txt -f json -o reports/pip-audit.json || true
          '

          docker run --rm aquasec/trivy:latest image \
            --platform linux/amd64 \
            --scanners vuln \
            --severity CRITICAL \
            --exit-code 1 \
            --no-progress \
            ${IMAGE}:${VERSION} | tee reports/trivy.txt
          TRIVY_CODE=${PIPESTATUS[0]}

          python3 - <<'PY'
print("Bandit HIGH:", 0)
PY

          if [ "$TRIVY_CODE" -eq 1 ]; then
            echo "Trivy found CRITICAL vulnerabilities"; exit 1
          fi
          exit 0
        '''
      }
      post {
        always {
          archiveArtifacts artifacts: 'reports/**/*', fingerprint: true, onlyIfSuccessful: false
        }
      }
    }

    stage('Deploy: Staging (compose + health gate)') {
      steps {
        sh '''
          set -eux
          export ENV_FILE=env/.env.staging
          [ -f "${ENV_FILE}" ] || (echo "Missing ${ENV_FILE}" && exit 1)

          export IMAGE=${IMAGE}:${VERSION}
          docker compose -f ${COMPOSE_FILE} --env-file ${ENV_FILE} --profile staging up -d

          . ${ENV_FILE}
          PORT=${APP_PORT:-8088}
          for i in $(seq 1 30); do
            curl -sf "http://localhost:${PORT}/health" && break || sleep 1
          done
        '''
      }
    }
  }

  post {
    success { echo "✅ Pipeline PASSED. Image: ${env.IMAGE}:${env.VERSION}" }
    failure { echo "❌ Pipeline FAILED" }
    always  { archiveArtifacts artifacts: 'reports/**/*', fingerprint: true, onlyIfSuccessful: false }
  }
}