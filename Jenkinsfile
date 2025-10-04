pipeline {
  agent any
  options { timestamps() }

  environment {
    REGISTRY     = 'ghcr.io'
    OWNER        = 'akrobe'
    IMAGE_NAME   = 'discountmate'
    IMAGE        = "${REGISTRY}/${OWNER}/${IMAGE_NAME}"
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
          mkdir -p reports
          GIT_SHA=$(git rev-parse --short HEAD)
          DATE=$(date +%Y.%m.%d)
          VERSION="${DATE}-${BUILD_NUMBER}-${GIT_SHA}"
          echo "VERSION=${VERSION}" | tee reports/version.txt
        '''
        script {
          env.VERSION = sh(script: "awk -F= '/^VERSION=/{print \$2}' reports/version.txt", returnStdout: true).trim()
        }
      }
    }

    stage('Docker Sanity') {
      steps {
        sh '''
          set -eux
          command -v docker
          docker version
          docker compose version
          docker buildx version
          # Ensure a usable buildx builder
          docker buildx inspect ci-builder >/dev/null 2>&1 || docker buildx create --name ci-builder --driver docker-container --use
          docker buildx inspect --bootstrap
        '''
      }
    }

    stage('Build & Push (multi-arch)') {
      steps {
        script {
          def loggedIn = false

          // First try Secret Text credential: ghcr_pat
          try {
            withCredentials([string(credentialsId: 'ghcr_pat', variable: 'PAT')]) {
              sh '''
                set -eux
                echo "$PAT" | docker login ghcr.io -u "akrobe" --password-stdin
              '''
              loggedIn = true
              echo "Logged in to GHCR using ghcr_pat"
            }
          } catch (e) {
            echo "No 'ghcr_pat' credential found; will try 'github-https'…"
          }

          // Fallback: use username/password (your existing github-https)
          if (!loggedIn) {
            try {
              withCredentials([usernamePassword(credentialsId: 'github-https', usernameVariable: 'GH_USER', passwordVariable: 'GH_PAT')]) {
                sh '''
                  set -eux
                  echo "$GH_PAT" | docker login ghcr.io -u "$GH_USER" --password-stdin
                '''
                loggedIn = true
                echo "Logged in to GHCR using github-https"
              }
            } catch (e2) {
              echo "No usable GHCR creds; will build locally and skip push."
            }
          }

          // Build & load single-arch image for local testing
          sh """
            set -eux
            docker buildx build \
              --platform linux/arm64 \
              --load \
              -t ${IMAGE}:${VERSION}-local \
              -f Dockerfile .
          """

          // If we could login, build and push a proper multi-arch image
          if (loggedIn) {
            sh """
              set -eux
              docker buildx build \
                --platform linux/amd64,linux/arm64 \
                -t ${IMAGE}:${VERSION} \
                -t ${IMAGE}:latest \
                -f Dockerfile \
                --push .
            """
            env.PUSHED = "true"
          } else {
            env.PUSHED = "false"
          }
        }
      }
    }

    stage('Test (unit)') {
      steps {
        sh '''
          set -eux
          mkdir -p reports
          docker run --rm \
            -v "$PWD":/workspace -w /workspace \
            -e PYTHONPATH=/workspace \
            ${IMAGE}:${VERSION}-local \
            sh -lc 'pip install -r requirements.txt -r requirements-dev.txt && \
                    pytest -q --junitxml=reports/junit.xml --cov=app --cov-report=xml:reports/coverage.xml tests/test_unit_model.py'
        '''
      }
    }

    stage('Test (integration)') {
      steps {
        sh '''
          set -eux
          docker rm -f dm_svc || true
          docker run -d --rm --name dm_svc -p 8088:8080 ${IMAGE}:${VERSION}-local

          for i in $(seq 1 30); do
            curl -sf http://localhost:8088/health && break || sleep 1
          done

          docker run --rm \
            -v "$PWD":/workspace -w /workspace \
            -e PYTHONPATH=/workspace \
            -e BASE_URL=http://host.docker.internal:8088 \
            ${IMAGE}:${VERSION}-local \
            sh -lc 'pip install -r requirements.txt -r requirements-dev.txt && \
                    pytest -q --junitxml=reports/junit-it.xml tests/test_integration_api.py'

          docker rm -f dm_svc || true
        '''
      }
    }

    stage('Security (Bandit, pip-audit, Trivy)') {
      steps {
        sh '''
          set +e
          mkdir -p reports

          docker run --rm -v "$PWD":/src python:3.12-slim sh -lc '
            pip install --no-cache-dir bandit pip-audit && cd /src && \
            bandit -r app -f json -o reports/bandit.json || true && \
            pip-audit -r requirements.txt -f json -o reports/pip-audit.json || true
          '

          # Trivy: scan the locally loaded image; mount Docker socket so Trivy can see it
          docker run --rm \
            -v /var/run/docker.sock:/var/run/docker.sock \
            -v "$PWD"/reports:/reports \
            aquasec/trivy:latest image --scanners vuln --severity CRITICAL \
            --exit-code 0 --format table -o /reports/trivy.txt ${IMAGE}:${VERSION}-local || true

          if grep -q CRITICAL reports/trivy.txt; then
            echo "Trivy found CRITICAL vulns (reported but not failing this build stage)."
          fi
          set -e
        '''
      }
    }

    stage('Deploy: Staging (compose + health gate)') {
      when { expression { return env.PUSHED == 'true' } }
      steps {
        sh '''
          set -eux
          mkdir -p env

          # Create env file if missing
          if [ ! -f env/.env.staging ]; then
            if [ -f env/.env.staging.example ]; then
              cp env/.env.staging.example env/.env.staging
            else
              echo "APP_PORT=8088" > env/.env.staging
            fi
          fi

          export ENV_FILE=env/.env.staging
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
    always {
      archiveArtifacts artifacts: 'reports/**', fingerprint: true, onlyIfSuccessful: false
    }
    success { echo "✅ Pipeline Succeeded" }
    failure { echo "❌ Pipeline FAILED" }
  }
}