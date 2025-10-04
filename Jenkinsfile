pipeline {
  agent any

  // --- Global options & params
  options {
    timestamps()
    disableConcurrentBuilds() // avoid approving an older run while a newer one exists
  }

  parameters {
     booleanParam(name: 'DEPLOY_STAGING', defaultValue: true, description: 'Deploy to staging after a successful push')
    booleanParam(name: 'DEPLOY_TO_PROD',    defaultValue: false, description: 'Enable the Prod release stage for this run')
    booleanParam(name: 'AUTO_APPROVE_PROD', defaultValue: false, description: 'Skip manual approval (no pause) when releasing to Prod')
    string(name: 'ROLLBACK_TO_VERSION', defaultValue: '', description: 'Optional: version to rollback to (e.g. 2025.10.04-26-39308f7)')
  }

  environment {
    // ---- Make Docker CLI visible to Jenkins regardless of launch PATH
    PATH = "/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin:/usr/bin:/bin:/usr/sbin:/sbin:${env.PATH}"

    REGISTRY   = 'ghcr.io'
    OWNER      = 'akrobe'
    IMAGE_NAME = 'discountmate'
    IMAGE      = "${REGISTRY}/${OWNER}/${IMAGE_NAME}"

    // Compose files
    COMPOSE_FILE       = 'compose.yaml'        // minimal staging compose (8088)
    COMPOSE_FILE_PROD  = 'docker-compose.yml'  // full compose (we deploy only the app service)

    // default so `when { expression { env.PUSHED == "true" } }` is safe
    PUSHED = 'false'
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
          echo "PATH is: $PATH"

          # 1) CLI must be present
          if ! command -v docker >/dev/null 2>&1; then
            echo "ERROR: docker CLI not found in PATH."
            echo "Checked /usr/local/bin, /opt/homebrew/bin and /Applications/Docker.app/Contents/Resources/bin"
            ls -l /Applications/Docker.app/Contents/Resources/bin || true
            exit 2
          fi

          # 2) Docker Desktop must be running (daemon reachable)
          docker version
          docker info >/dev/null

          # 3) Compose & buildx available
          docker compose version
          docker buildx version || true

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

          // Prefer a Secret Text called ghcr_pat (PAT with write:packages)
          try {
            withCredentials([string(credentialsId: 'ghcr_pat', variable: 'PAT')]) {
              sh '''
                set -eux
                echo "$PAT" | docker login ghcr.io -u "akrobe" --password-stdin
              '''
              loggedIn = true
              echo "Logged in to GHCR using ghcr_pat"
            }
          } catch (ignore) {
            echo "No 'ghcr_pat' credential found; will try 'github-https'…"
          }

          // Fallback to your existing username/password credential
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
            } catch (ignore2) {
              echo "No usable GHCR creds; will build locally and skip push."
            }
          }

          // Build a local image (single-arch) for tests
          sh """
            set -eux
            docker buildx build \
              --platform linux/arm64 \
              --load \
              -t ${IMAGE}:${VERSION}-local \
              -f Dockerfile .
          """

          // If logged in, build & push multi-arch
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

          # Make sure no old tester containers are around (any port)
          docker rm -f dm_svc || true

          # Start test container on a RANDOM free host port
          docker run -d --rm --name dm_svc -p 0:8080 ghcr.io/akrobe/discountmate:${VERSION}-local

          # Discover the port that Docker assigned on the host
          HOST_PORT=$(docker port dm_svc 8080/tcp | head -n1 | awk -F: '{print $NF}')
          echo "Using HOST_PORT=$HOST_PORT"

          # Wait for health
          for i in $(seq 1 30); do
            curl -fsS "http://localhost:${HOST_PORT}/health" && break || sleep 1
          done

          # Run integration tests against that dynamic port
          docker run --rm \
            -v "$WORKSPACE":/workspace -w /workspace \
            -e PYTHONPATH=/workspace \
            -e BASE_URL="http://host.docker.internal:${HOST_PORT}" \
            ghcr.io/akrobe/discountmate:${VERSION}-local sh -lc '
              pip install -r requirements.txt -r requirements-dev.txt &&
              pytest -q --junitxml=reports/junit-it.xml tests/test_integration_api.py
            '

          # Stop container (it has --rm so it will be removed)
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

          # Scan local image via Docker socket
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
  when {
    beforeAgent true
    allOf {
      expression { env.PUSHED?.trim() == 'true' }   // image was pushed
      expression { params.DEPLOY_STAGING }          // user wants staging
    }
  }
  steps {
    // 👇 replace your /* unchanged */ with something like this:
    sh """
      set -eux
      mkdir -p env
      [ -f env/.env.staging ] || echo "APP_PORT=8088" > env/.env.staging

      export ENV_FILE=env/.env.staging
      export IMAGE=${IMAGE}:${VERSION}

      docker compose -f ${COMPOSE_FILE} --env-file "$ENV_FILE" up -d

      # Health gate on 8088
      for i in \$(seq 1 30); do
        curl -sf http://localhost:8088/health && break || sleep 1
      done
    """
  }
}

stage('Gate Debug') {
  steps {
    echo "PUSHED=${env.PUSHED} DEPLOY_TO_PROD=${params.DEPLOY_TO_PROD} AUTO_APPROVE_PROD=${params.AUTO_APPROVE_PROD}"
  }
}

stage('Release: Prod') {
  when {
    beforeAgent true
    allOf {
      expression { env.PUSHED?.trim() == 'true' }
      expression { params.DEPLOY_TO_PROD }   // <-- fix here
    }
  }
      steps {
        script {
          // Ensure we’re logged in to GHCR
          def loggedIn = false
          try {
            withCredentials([string(credentialsId: 'ghcr_pat', variable: 'PAT')]) {
              sh 'echo "$PAT" | docker login ghcr.io -u "akrobe" --password-stdin'
              loggedIn = true
            }
          } catch (ignore) { /* fall through */ }
          if (!loggedIn) {
            withCredentials([usernamePassword(credentialsId: 'github-https', usernameVariable: 'GH_USER', passwordVariable: 'GH_PAT')]) {
              sh 'echo "$GH_PAT" | docker login ghcr.io -u "$GH_USER" --password-stdin'
              loggedIn = true
            }
          }

          sh """
            set -eux
            mkdir -p env
            [ -f env/.env.production ] || echo "APP_PORT=80" > env/.env.production

            # Pull exact version built in this run, tag as :prod, push
            docker pull ${IMAGE}:${VERSION}
            docker tag  ${IMAGE}:${VERSION} ${IMAGE}:prod
            docker push ${IMAGE}:prod

            # Deploy JUST the app service to avoid monitoring mount issues
            export ENV_FILE=env/.env.production
            export IMAGE=${IMAGE}:${VERSION}

            docker compose -f ${COMPOSE_FILE_PROD} --env-file "$ENV_FILE" --profile prod up -d discountmate

            # Smoke test port 80
            for i in \$(seq 1 30); do
              curl -sf http://localhost/health && break || sleep 1
            done
          """
        }
      }
    }

    // ---------- One-click manual rollback
    stage('Rollback (manual)') {
      when {
        expression { return params.ROLLBACK_TO_VERSION ?: '').trim() != '' }
      }
      steps {
        timeout(time: 2, unit: 'HOURS') {
          input message: "Rollback PRODUCTION to ${params.ROLLBACK_TO_VERSION}?", ok: 'Rollback'
        }
        script {
          // Login (same logic, keeps things self-contained)
          def loggedIn = false
          try {
            withCredentials([string(credentialsId: 'ghcr_pat', variable: 'PAT')]) {
              sh 'echo "$PAT" | docker login ghcr.io -u "akrobe" --password-stdin'
              loggedIn = true
            }
          } catch (ignore) { /* fall through */ }
          if (!loggedIn) {
            withCredentials([usernamePassword(credentialsId: 'github-https', usernameVariable: 'GH_USER', passwordVariable: 'GH_PAT')]) {
              sh 'echo "$GH_PAT" | docker login ghcr.io -u "$GH_USER" --password-stdin'
              loggedIn = true
            }
          }

          sh """
            set -eux
            mkdir -p env
            [ -f env/.env.production ] || echo "APP_PORT=80" > env/.env.production

            export ENV_FILE=env/.env.production
            export IMAGE=${IMAGE}:${params.ROLLBACK_TO_VERSION}

            docker pull ${IMAGE}

            # Redeploy only the app service
            docker compose -f ${COMPOSE_FILE_PROD} --env-file "$ENV_FILE" --profile prod up -d discountmate

            # Smoke test port 80
            for i in \$(seq 1 30); do
              curl -sf http://localhost/health && break || sleep 1
            done
          """
        }
      }
    }
  }

  post {
    always {
      archiveArtifacts artifacts: 'reports/**', fingerprint: true, onlyIfSuccessful: false
    }
    success { echo "Pipeline Succeeded" }
    failure { echo "Pipeline FAILED" }
  }
}