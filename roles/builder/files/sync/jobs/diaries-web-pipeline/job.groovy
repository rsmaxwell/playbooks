multibranchPipelineJob('diaries-web-pipeline') {
    branchSources {
        git {
            id = 'diaries-web-pipeline'
            remote('https://github.com/rsmaxwell/diaries-web-pipeline.git')
        }
    }
}
